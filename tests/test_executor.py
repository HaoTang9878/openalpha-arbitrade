"""
交易执行器单元测试

覆盖 backend/executor.py 的核心方法：
- _execute_paper_trade() — 模拟交易计算利润
- get_trade_history() — 交易历史查询
- _handle_partial_failure() — 部分失败处理
- execute() — 主入口（模拟交易模式）
- _get_exchange() — 交易所实例创建
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.config import Config
from backend.executor import TradeExecutor
from backend.models import ArbitrageOpportunity, OrderStatus, RiskLevel, TradeResult


# ----------------------------------------------------------------------------
# _execute_paper_trade() 模拟交易测试
# ----------------------------------------------------------------------------
class TestPaperTrade:
    """_execute_paper_trade() 模拟交易测试"""

    @pytest.mark.asyncio
    async def test_paper_trade_calculates_profit(self, test_config, sample_opportunity):
        """模拟交易正确计算利润（扣除双边手续费）"""
        executor = TradeExecutor(test_config)
        result = await executor.execute(sample_opportunity)

        assert result.paper_trade is True
        assert result.status == OrderStatus.FILLED
        assert result.symbol == sample_opportunity.symbol
        assert result.buy_exchange == sample_opportunity.buy_exchange
        assert result.sell_exchange == sample_opportunity.sell_exchange
        assert result.buy_price == sample_opportunity.buy_price
        assert result.sell_price == sample_opportunity.sell_price
        assert result.amount == test_config.model.order_amount

        # 验证利润计算
        amount = test_config.model.order_amount
        buy_cost = sample_opportunity.buy_price * amount
        sell_revenue = sample_opportunity.sell_price * amount
        buy_fee = buy_cost * test_config.get_exchange_fee(sample_opportunity.buy_exchange)
        sell_fee = sell_revenue * test_config.get_exchange_fee(sample_opportunity.sell_exchange)
        expected_profit = sell_revenue - buy_cost - buy_fee - sell_fee
        assert result.profit == pytest.approx(round(expected_profit, 6))

    @pytest.mark.asyncio
    async def test_paper_trade_generates_order_ids(self, test_config, sample_opportunity):
        """模拟交易生成 PAPER 订单 ID"""
        executor = TradeExecutor(test_config)
        result = await executor.execute(sample_opportunity)
        assert result.buy_order_id is not None
        assert result.buy_order_id.startswith("PAPER-BUY-")
        assert result.sell_order_id is not None
        assert result.sell_order_id.startswith("PAPER-SELL-")
        # 买卖订单 ID 后缀一致（同一 trade_id）
        assert result.buy_order_id.split("-")[-1] == result.sell_order_id.split("-")[-1]

    @pytest.mark.asyncio
    async def test_paper_trade_appends_to_history(self, test_config, sample_opportunity):
        """模拟交易追加到内存历史"""
        executor = TradeExecutor(test_config)
        await executor.execute(sample_opportunity)
        assert len(executor.trade_history) == 1

    @pytest.mark.asyncio
    async def test_paper_trade_persists_to_database(self, test_config, sample_opportunity, tmp_db):
        """传入 database 时模拟交易持久化"""
        executor = TradeExecutor(test_config, database=tmp_db)
        result = await executor.execute(sample_opportunity)
        # 从数据库查询验证
        trades = tmp_db.get_trades(10)
        assert len(trades) == 1
        assert trades[0]["id"] == result.id

    @pytest.mark.asyncio
    async def test_paper_trade_negative_profit(self, test_config):
        """模拟交易亏损时利润为负"""
        # 构造卖价低于买价的机会
        op = ArbitrageOpportunity(
            symbol="BTC/USDT", buy_exchange="binance", sell_exchange="okx",
            buy_price=96000.0, sell_price=95000.0,
            spread_percent=-0.0104, net_profit_rate=-0.0124,
            estimated_profit=-11.9, risk_level=RiskLevel.HIGH,
            timestamp=1700000000000,
        )
        executor = TradeExecutor(test_config)
        result = await executor.execute(op)
        assert result.profit < 0

    @pytest.mark.asyncio
    async def test_execute_uses_paper_mode_when_configured(self, test_config, sample_opportunity):
        """paper_trade=True 时走模拟交易路径"""
        test_config.model.paper_trade = True
        executor = TradeExecutor(test_config)
        result = await executor.execute(sample_opportunity)
        assert result.paper_trade is True

    @pytest.mark.asyncio
    async def test_paper_trade_unique_trade_id(self, test_config, sample_opportunity):
        """每次模拟交易生成唯一 trade_id"""
        executor = TradeExecutor(test_config)
        r1 = await executor.execute(sample_opportunity)
        r2 = await executor.execute(sample_opportunity)
        assert r1.id != r2.id


# ----------------------------------------------------------------------------
# get_trade_history() 交易历史查询测试
# ----------------------------------------------------------------------------
class TestGetTradeHistory:
    """get_trade_history() 交易历史查询测试"""

    @pytest.mark.asyncio
    async def test_get_history_from_memory(self, test_config, sample_opportunity):
        """无数据库时从内存缓存查询"""
        executor = TradeExecutor(test_config)
        await executor.execute(sample_opportunity)
        await executor.execute(sample_opportunity)
        history = executor.get_trade_history(limit=10)
        assert len(history) == 2
        assert all(isinstance(t, TradeResult) for t in history)

    @pytest.mark.asyncio
    async def test_get_history_from_database(self, test_config, sample_opportunity, tmp_db):
        """有数据库时优先从数据库查询"""
        executor = TradeExecutor(test_config, database=tmp_db)
        await executor.execute(sample_opportunity)
        # 清空内存缓存，强制走数据库
        executor.trade_history.clear()
        history = executor.get_trade_history(limit=10)
        assert len(history) == 1
        assert isinstance(history[0], TradeResult)

    @pytest.mark.asyncio
    async def test_get_history_limit(self, test_config, sample_opportunity):
        """get_trade_history 限制返回数量"""
        executor = TradeExecutor(test_config)
        for _ in range(5):
            await executor.execute(sample_opportunity)
        history = executor.get_trade_history(limit=3)
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_get_history_empty(self, test_config):
        """无交易历史时返回空列表"""
        executor = TradeExecutor(test_config)
        assert executor.get_trade_history() == []

    @pytest.mark.asyncio
    async def test_get_history_ordered_desc(self, test_config, sample_opportunity):
        """内存历史按时间倒序返回（最新在前）"""
        executor = TradeExecutor(test_config)
        results = []
        for _ in range(3):
            r = await executor.execute(sample_opportunity)
            results.append(r)
        history = executor.get_trade_history(limit=10)
        # 最新的在前
        assert history[0].id == results[-1].id
        assert history[-1].id == results[0].id


# ----------------------------------------------------------------------------
# _handle_partial_failure() 部分失败处理测试
# ----------------------------------------------------------------------------
class TestHandlePartialFailure:
    """_handle_partial_failure() 部分失败处理测试"""

    def test_buy_failed_sell_ok(self, test_config, sample_opportunity):
        """买入失败、卖出成功时取消卖出单"""
        executor = TradeExecutor(test_config)
        with patch("asyncio.create_task") as mock_task:
            error_msg = executor._handle_partial_failure(
                buy_ok=False, sell_ok=True,
                buy_order_id=Exception("buy error"),
                sell_order_id="sell_order_123",
                opportunity=sample_opportunity,
            )
        assert "买入下单失败" in error_msg
        assert "已取消卖出单" in error_msg
        mock_task.assert_called_once()

    def test_sell_failed_buy_ok(self, test_config, sample_opportunity):
        """卖出失败、买入成功时取消买入单"""
        executor = TradeExecutor(test_config)
        with patch("asyncio.create_task") as mock_task:
            error_msg = executor._handle_partial_failure(
                buy_ok=True, sell_ok=False,
                buy_order_id="buy_order_123",
                sell_order_id=Exception("sell error"),
                opportunity=sample_opportunity,
            )
        assert "卖出下单失败" in error_msg
        assert "已取消买入单" in error_msg
        mock_task.assert_called_once()

    def test_both_failed(self, test_config, sample_opportunity):
        """双边都失败时不取消任何订单"""
        executor = TradeExecutor(test_config)
        with patch("asyncio.create_task") as mock_task:
            error_msg = executor._handle_partial_failure(
                buy_ok=False, sell_ok=False,
                buy_order_id=Exception("buy error"),
                sell_order_id=Exception("sell error"),
                opportunity=sample_opportunity,
            )
        # 不应调用 create_task（无单可取消）
        mock_task.assert_not_called()
        assert "买入下单失败" in error_msg

    def test_buy_failed_sell_not_str(self, test_config, sample_opportunity):
        """卖出订单 ID 非字符串时不尝试取消"""
        executor = TradeExecutor(test_config)
        with patch("asyncio.create_task") as mock_task:
            executor._handle_partial_failure(
                buy_ok=False, sell_ok=True,
                buy_order_id=Exception("buy error"),
                sell_order_id=12345,  # 非字符串
                opportunity=sample_opportunity,
            )
        mock_task.assert_not_called()


# ----------------------------------------------------------------------------
# _get_exchange() 交易所实例创建测试
# ----------------------------------------------------------------------------
class TestGetExchange:
    """_get_exchange() 交易所实例创建测试"""

    def test_get_exchange_creates_instance(self, test_config):
        """创建已知交易所实例"""
        executor = TradeExecutor(test_config)
        exchange = executor._get_exchange("binance")
        assert exchange is not None
        assert "binance" in executor._exchange_instances

    def test_get_exchange_caches_instance(self, test_config):
        """重复获取返回同一实例（缓存）"""
        executor = TradeExecutor(test_config)
        ex1 = executor._get_exchange("binance")
        ex2 = executor._get_exchange("binance")
        assert ex1 is ex2

    def test_get_exchange_unsupported_returns_none(self, test_config):
        """不支持的交易所返回 None"""
        executor = TradeExecutor(test_config)
        exchange = executor._get_exchange("nonexistent_exchange")
        assert exchange is None

    def test_get_exchange_with_api_keys(self, test_config):
        """传入 API 密钥时注入配置"""
        test_config.api_keys["binance"] = {"apiKey": "test_key", "secret": "test_secret"}
        executor = TradeExecutor(test_config, api_keys=test_config.api_keys)
        exchange = executor._get_exchange("binance")
        assert exchange is not None


# ----------------------------------------------------------------------------
# 实盘交易路径测试（mock CCXT）
# ----------------------------------------------------------------------------
class TestRealTradePath:
    """实盘交易路径测试（mock CCXT，不实际请求网络）"""

    @pytest.mark.asyncio
    async def test_real_trade_insufficient_balance(self, test_config, sample_opportunity, tmp_db):
        """余额不足时实盘交易返回 FAILED"""
        test_config.model.paper_trade = False
        executor = TradeExecutor(test_config, database=tmp_db)

        # mock check_balance 返回 False
        executor.check_balance = AsyncMock(return_value=False)
        result = await executor.execute(sample_opportunity)

        assert result.status == OrderStatus.FAILED
        assert result.error == "余额不足"
        assert result.paper_trade is False

    @pytest.mark.asyncio
    async def test_real_trade_success(self, test_config, sample_opportunity):
        """实盘交易成功（mock 全流程）"""
        test_config.model.paper_trade = False
        executor = TradeExecutor(test_config)

        # mock 余额检查通过
        executor.check_balance = AsyncMock(return_value=True)
        # mock 下单成功
        executor.place_order = AsyncMock(side_effect=["buy_id_123", "sell_id_456"])
        # mock 订单状态查询（已成交）
        executor.get_order_status = AsyncMock(side_effect=[
            {"status": "closed", "average": sample_opportunity.buy_price},
            {"status": "closed", "average": sample_opportunity.sell_price},
        ])

        result = await executor.execute(sample_opportunity)
        assert result.status == OrderStatus.FILLED
        assert result.buy_order_id == "buy_id_123"
        assert result.sell_order_id == "sell_id_456"
        assert result.paper_trade is False

    @pytest.mark.asyncio
    async def test_real_trade_partial_fill(self, test_config, sample_opportunity):
        """实盘交易部分成交返回 PARTIALLY_FILLED"""
        test_config.model.paper_trade = False
        executor = TradeExecutor(test_config)

        executor.check_balance = AsyncMock(return_value=True)
        executor.place_order = AsyncMock(side_effect=["buy_id", "sell_id"])
        # 一边未完全成交
        executor.get_order_status = AsyncMock(side_effect=[
            {"status": "closed", "average": sample_opportunity.buy_price},
            {"status": "open", "average": 0},
        ])

        result = await executor.execute(sample_opportunity)
        assert result.status == OrderStatus.PARTIALLY_FILLED

    @pytest.mark.asyncio
    async def test_real_trade_buy_order_fails(self, test_config, sample_opportunity):
        """买入下单失败时触发部分失败处理"""
        test_config.model.paper_trade = False
        executor = TradeExecutor(test_config)

        executor.check_balance = AsyncMock(return_value=True)
        # 买入失败（抛异常），卖出成功
        executor.place_order = AsyncMock(side_effect=[RuntimeError("buy failed"), "sell_id"])
        executor.cancel_order = AsyncMock(return_value=None)

        result = await executor.execute(sample_opportunity)
        assert result.status == OrderStatus.FAILED
        assert "买入下单失败" in (result.error or "")


# ----------------------------------------------------------------------------
# close() 关闭测试
# ----------------------------------------------------------------------------
class TestExecutorClose:
    """close() 关闭交易所连接测试"""

    @pytest.mark.asyncio
    async def test_close_clears_instances(self, test_config):
        """close 清空交易所实例缓存"""
        executor = TradeExecutor(test_config)
        # 创建一个实例
        executor._get_exchange("binance")
        assert len(executor._exchange_instances) > 0
        await executor.close()
        assert len(executor._exchange_instances) == 0

    @pytest.mark.asyncio
    async def test_close_handles_errors(self, test_config):
        """close 时单个交易所关闭失败不影响其他"""
        executor = TradeExecutor(test_config)
        mock_ex = MagicMock()
        mock_ex.close = AsyncMock(side_effect=Exception("close failed"))
        executor._exchange_instances["mock"] = mock_ex
        # 不应抛异常
        await executor.close()
        assert len(executor._exchange_instances) == 0
