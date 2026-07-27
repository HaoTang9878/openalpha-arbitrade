"""
交易执行器模块

负责执行套利交易，支持两种模式：
1. 模拟交易（Paper Trade）- 记录但不实际下单，用于策略验证
2. 实盘交易 - 通过 CCXT 在两个交易所同时下单

执行流程（参考 Hummingbot）：
1. 检查双边余额是否充足
2. 在低价交易所提交买入限价单
3. 在高价交易所提交卖出限价单
4. 追踪订单状态，超时取消
5. 记录交易日志

使用方法：
    executor = TradeExecutor(config, api_keys)
    result = await executor.execute(opportunity)
"""

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

import ccxt.async_support as ccxt

from .config import Config
from .models import ArbitrageOpportunity, OrderStatus, TradeResult

logger = logging.getLogger(__name__)

# 订单状态轮询间隔（秒）
ORDER_POLL_INTERVAL = 2


class TradeExecutor:
    """
    交易执行器

    负责执行套利交易的全流程：余额检查、双边下单、状态追踪、超时取消。
    支持模拟交易和实盘交易两种模式。
    """

    def __init__(
        self,
        config: Config,
        api_keys: Optional[Dict[str, Dict[str, str]]] = None,
        database: Optional[Any] = None,
    ) -> None:
        """
        初始化交易执行器

        Args:
            config: 系统配置管理器
            api_keys: 各交易所的 API 密钥字典
            database: 可选的 SQLite 持久化层实例（backend.database.Database），
                      传入后交易历史将自动持久化并优先从数据库查询
        """
        self.config = config
        self.api_keys = api_keys or {}
        self.database = database

        # 交易历史记录（内存缓存，数据库可用时仅作为回退）
        self.trade_history: List[TradeResult] = []

        # 各交易所的 CCXT 实例（延迟初始化）
        self._exchange_instances: Dict[str, ccxt.Exchange] = {}

        logger.info(
            "交易执行器初始化完成，模式: %s",
            "模拟交易" if self.config.model.paper_trade else "实盘交易",
        )

    def _get_exchange(self, exchange_name: str) -> Optional[ccxt.Exchange]:
        """
        获取或创建交易所实例（延迟初始化）

        Args:
            exchange_name: 交易所名称

        Returns:
            CCXT 交易所实例，失败返回 None
        """
        if exchange_name in self._exchange_instances:
            return self._exchange_instances[exchange_name]

        try:
            exchange_class = getattr(ccxt, exchange_name, None)
            if exchange_class is None:
                logger.error("不支持的交易所: %s", exchange_name)
                return None

            exchange_config: Dict[str, Any] = {
                "enableRateLimit": True,
                "timeout": 5000,
                "options": {"defaultType": "spot"},
            }

            if exchange_name in self.api_keys:
                exchange_config.update(self.api_keys[exchange_name])

            instance = exchange_class(exchange_config)
            self._exchange_instances[exchange_name] = instance
            return instance

        except Exception as e:
            logger.error("创建交易所 %s 实例失败: %s", exchange_name, e,
                         exc_info=True)
            return None

    async def execute(self, opportunity: ArbitrageOpportunity) -> TradeResult:
        """
        执行套利交易

        根据配置选择模拟交易或实盘交易模式。
        模拟交易只记录日志和结果，不实际下单。

        Args:
            opportunity: 套利机会对象

        Returns:
            交易结果对象
        """
        trade_id = str(uuid.uuid4())[:8]
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        amount = self.config.model.order_amount

        logger.info(
            "开始执行套利: %s 买入@%s(%.4f) 卖出@%s(%.4f) 数量=%.4f",
            opportunity.symbol,
            opportunity.buy_exchange, opportunity.buy_price,
            opportunity.sell_exchange, opportunity.sell_price,
            amount,
        )

        # 模拟交易模式：只记录不执行
        if self.config.model.paper_trade:
            return self._execute_paper_trade(opportunity, trade_id, timestamp, amount)

        # 实盘交易模式
        return await self._execute_real_trade(opportunity, trade_id, timestamp, amount)

    def _execute_paper_trade(
        self,
        opportunity: ArbitrageOpportunity,
        trade_id: str,
        timestamp: str,
        amount: float,
    ) -> TradeResult:
        """
        执行模拟交易

        不实际下单，直接根据套利机会的理论价格计算模拟利润。

        Args:
            opportunity: 套利机会
            trade_id: 交易ID
            timestamp: 时间戳字符串
            amount: 交易数量

        Returns:
            模拟交易结果
        """
        buy_cost = opportunity.buy_price * amount
        sell_revenue = opportunity.sell_price * amount
        buy_fee = buy_cost * self.config.get_exchange_fee(opportunity.buy_exchange)
        sell_fee = sell_revenue * self.config.get_exchange_fee(opportunity.sell_exchange)
        profit = sell_revenue - buy_cost - buy_fee - sell_fee

        result = TradeResult(
            id=trade_id,
            symbol=opportunity.symbol,
            buy_exchange=opportunity.buy_exchange,
            sell_exchange=opportunity.sell_exchange,
            buy_price=opportunity.buy_price,
            sell_price=opportunity.sell_price,
            amount=amount,
            buy_order_id=f"PAPER-BUY-{trade_id}",
            sell_order_id=f"PAPER-SELL-{trade_id}",
            status=OrderStatus.FILLED,
            profit=round(profit, 6),
            paper_trade=True,
            timestamp=timestamp,
        )

        self.trade_history.append(result)
        if self.database:
            self.database.save_trade(result)
        logger.info(
            "模拟交易完成: %s 利润=%.4f USDT (净利润率=%.4f%%)",
            opportunity.symbol, profit, opportunity.net_profit_rate * 100,
        )
        return result

    async def _execute_real_trade(
        self,
        opportunity: ArbitrageOpportunity,
        trade_id: str,
        timestamp: str,
        amount: float,
    ) -> TradeResult:
        """
        执行实盘交易

        流程：
        1. 检查双边余额
        2. 同时提交买入和卖出限价单
        3. 等待订单成交或超时
        4. 计算实际利润

        Args:
            opportunity: 套利机会
            trade_id: 交易ID
            timestamp: 时间戳字符串
            amount: 交易数量

        Returns:
            交易结果对象
        """
        # 解析交易对的基础货币和计价货币（如 BTC/USDT -> BTC, USDT）
        base_currency, quote_currency = opportunity.symbol.split("/")

        # 检查余额
        balance_ok = await self._check_balances(
            opportunity, base_currency, quote_currency, amount
        )
        if not balance_ok:
            result = TradeResult(
                id=trade_id,
                symbol=opportunity.symbol,
                buy_exchange=opportunity.buy_exchange,
                sell_exchange=opportunity.sell_exchange,
                amount=amount,
                status=OrderStatus.FAILED,
                error="余额不足",
                paper_trade=False,
                timestamp=timestamp,
            )
            self.trade_history.append(result)
            if self.database:
                self.database.save_trade(result)
            return result

        # 同时提交买入和卖出限价单
        buy_task = self.place_order(
            opportunity.buy_exchange, opportunity.symbol,
            "buy", amount, opportunity.buy_price,
        )
        sell_task = self.place_order(
            opportunity.sell_exchange, opportunity.symbol,
            "sell", amount, opportunity.sell_price,
        )

        buy_order_id, sell_order_id = await asyncio.gather(
            buy_task, sell_task, return_exceptions=True
        )

        # 处理下单结果
        buy_ok = isinstance(buy_order_id, str)
        sell_ok = isinstance(sell_order_id, str)

        if not buy_ok or not sell_ok:
            # 一边失败需要取消另一边的订单
            error_msg = self._handle_partial_failure(
                buy_ok, sell_ok, buy_order_id, sell_order_id,
                opportunity,
            )
            result = TradeResult(
                id=trade_id,
                symbol=opportunity.symbol,
                buy_exchange=opportunity.buy_exchange,
                sell_exchange=opportunity.sell_exchange,
                amount=amount,
                buy_order_id=buy_order_id if buy_ok else None,
                sell_order_id=sell_order_id if sell_ok else None,
                status=OrderStatus.FAILED,
                error=error_msg,
                paper_trade=False,
                timestamp=timestamp,
            )
            self.trade_history.append(result)
            if self.database:
                self.database.save_trade(result)
            return result

        # 等待订单成交
        buy_status, sell_status = await self._wait_for_orders(
            opportunity.buy_exchange, buy_order_id,
            opportunity.sell_exchange, sell_order_id,
        )

        # 计算实际利润
        profit = 0.0
        final_status = OrderStatus.FILLED
        if buy_status.get("status") == "closed" and sell_status.get("status") == "closed":
            actual_buy = float(buy_status.get("average", opportunity.buy_price))
            actual_sell = float(sell_status.get("average", opportunity.sell_price))
            buy_fee = actual_buy * amount * self.config.get_exchange_fee(
                opportunity.buy_exchange
            )
            sell_fee = actual_sell * amount * self.config.get_exchange_fee(
                opportunity.sell_exchange
            )
            profit = (actual_sell - actual_buy) * amount - buy_fee - sell_fee
        else:
            final_status = OrderStatus.PARTIALLY_FILLED
            logger.warning("订单未完全成交: buy=%s sell=%s",
                           buy_status.get("status"), sell_status.get("status"))

        result = TradeResult(
            id=trade_id,
            symbol=opportunity.symbol,
            buy_exchange=opportunity.buy_exchange,
            sell_exchange=opportunity.sell_exchange,
            buy_price=opportunity.buy_price,
            sell_price=opportunity.sell_price,
            amount=amount,
            buy_order_id=buy_order_id,
            sell_order_id=sell_order_id,
            status=final_status,
            profit=round(profit, 6),
            paper_trade=False,
            timestamp=timestamp,
        )

        self.trade_history.append(result)
        if self.database:
            self.database.save_trade(result)
        logger.info("实盘交易完成: %s 利润=%.4f USDT 状态=%s",
                     opportunity.symbol, profit, final_status.value)
        return result

    async def _check_balances(
        self,
        opportunity: ArbitrageOpportunity,
        base_currency: str,
        quote_currency: str,
        amount: float,
    ) -> bool:
        """
        检查双边交易所的余额是否充足

        买入交易所需要有足够的计价货币（如 USDT），
        卖出交易所需要有足够的基础货币（如 BTC）。

        Args:
            opportunity: 套利机会
            base_currency: 基础货币
            quote_currency: 计价货币
            amount: 交易数量

        Returns:
            余额是否充足
        """
        try:
            # 检查买入交易所的计价货币余额
            buy_ok = await self.check_balance(
                opportunity.buy_exchange, quote_currency,
                opportunity.buy_price * amount,
            )

            # 检查卖出交易所的基础货币余额
            sell_ok = await self.check_balance(
                opportunity.sell_exchange, base_currency, amount,
            )

            if not buy_ok:
                logger.warning("买入交易所 %s 的 %s 余额不足",
                               opportunity.buy_exchange, quote_currency)
            if not sell_ok:
                logger.warning("卖出交易所 %s 的 %s 余额不足",
                               opportunity.sell_exchange, base_currency)

            return buy_ok and sell_ok

        except Exception as e:
            logger.error("检查余额失败: %s", e, exc_info=True)
            return False

    def _handle_partial_failure(
        self,
        buy_ok: bool,
        sell_ok: bool,
        buy_order_id: Any,
        sell_order_id: Any,
        opportunity: ArbitrageOpportunity,
    ) -> str:
        """
        处理部分下单失败的情况

        如果一边下单成功另一边失败，需要取消成功的那边订单以避免单边风险。

        Args:
            buy_ok: 买入是否成功
            sell_ok: 卖出是否成功
            buy_order_id: 买入订单ID
            sell_order_id: 卖出订单ID
            opportunity: 套利机会

        Returns:
            错误描述字符串
        """
        error_msg = ""
        if not buy_ok:
            error_msg = f"买入下单失败: {buy_order_id}"
            # 取消已提交的卖出单
            if sell_ok and isinstance(sell_order_id, str):
                asyncio.create_task(
                    self.cancel_order(opportunity.sell_exchange, sell_order_id)
                )
                error_msg += "，已取消卖出单"
        if not sell_ok:
            error_msg = f"卖出下单失败: {sell_order_id}"
            # 取消已提交的买入单
            if buy_ok and isinstance(buy_order_id, str):
                asyncio.create_task(
                    self.cancel_order(opportunity.buy_exchange, buy_order_id)
                )
                error_msg += "，已取消买入单"

        logger.error("部分下单失败: %s", error_msg)
        return error_msg

    async def _wait_for_orders(
        self,
        buy_exchange: str,
        buy_order_id: str,
        sell_exchange: str,
        sell_order_id: str,
    ) -> tuple:
        """
        等待双边订单成交或超时

        定期轮询订单状态，直到两边都成交或超过最大等待时间。

        Args:
            buy_exchange: 买入交易所
            buy_order_id: 买入订单ID
            sell_exchange: 卖出交易所
            sell_order_id: 卖出订单ID

        Returns:
            (买入订单状态, 卖出订单状态) 元组
        """
        max_wait = self.config.model.max_order_age
        elapsed = 0

        buy_status: Dict[str, Any] = {"status": "open"}
        sell_status: Dict[str, Any] = {"status": "open"}

        while elapsed < max_wait:
            try:
                buy_status, sell_status = await asyncio.gather(
                    self.get_order_status(buy_exchange, buy_order_id),
                    self.get_order_status(sell_exchange, sell_order_id),
                )

                # 两边都已成交则返回
                buy_closed = buy_status.get("status") in ("closed", "filled")
                sell_closed = sell_status.get("status") in ("closed", "filled")
                if buy_closed and sell_closed:
                    return buy_status, sell_status

                # 任一边已取消则返回
                if buy_status.get("status") in ("canceled", "cancelled", "expired"):
                    logger.warning("买入订单已取消: %s", buy_order_id)
                    return buy_status, sell_status
                if sell_status.get("status") in ("canceled", "cancelled", "expired"):
                    logger.warning("卖出订单已取消: %s", sell_order_id)
                    return buy_status, sell_status

            except Exception as e:
                logger.error("查询订单状态失败: %s", e, exc_info=True)

            await asyncio.sleep(ORDER_POLL_INTERVAL)
            elapsed += ORDER_POLL_INTERVAL

        # 超时，尝试取消未成交的订单
        logger.warning("订单超时未成交，尝试取消")
        await asyncio.gather(
            self.cancel_order(buy_exchange, buy_order_id),
            self.cancel_order(sell_exchange, sell_order_id),
            return_exceptions=True,
        )

        return buy_status, sell_status

    async def check_balance(
        self, exchange_name: str, asset: str, required_amount: float
    ) -> bool:
        """
        检查指定交易所的某个资产余额是否充足

        Args:
            exchange_name: 交易所名称
            asset: 资产名称（如 USDT, BTC）
            required_amount: 需要的数量

        Returns:
            余额是否充足
        """
        exchange = self._get_exchange(exchange_name)
        if exchange is None:
            return False

        try:
            balance = await exchange.fetch_balance()
            available = balance.get(asset, {}).get("free", 0)
            sufficient = float(available) >= required_amount
            logger.debug(
                "余额检查: %s %s 可用=%.6f 需要=%.6f 充足=%s",
                exchange_name, asset, available, required_amount, sufficient,
            )
            return sufficient
        except Exception as e:
            logger.error("查询 %s 的 %s 余额失败: %s",
                         exchange_name, asset, e, exc_info=True)
            return False

    async def place_order(
        self,
        exchange_name: str,
        symbol: str,
        side: str,
        amount: float,
        price: float,
    ) -> str:
        """
        在指定交易所提交限价订单

        Args:
            exchange_name: 交易所名称
            symbol: 交易对
            side: 买卖方向（"buy" 或 "sell"）
            amount: 下单数量
            price: 限价价格

        Returns:
            订单ID字符串
        """
        exchange = self._get_exchange(exchange_name)
        if exchange is None:
            raise RuntimeError(f"交易所 {exchange_name} 未初始化")

        try:
            order = await exchange.create_limit_order(
                symbol, side, amount, price
            )
            order_id = str(order.get("id", ""))
            logger.info(
                "下单成功: %s %s %s %.4f @ %.4f 订单ID=%s",
                exchange_name, side, symbol, amount, price, order_id,
            )
            return order_id
        except Exception as e:
            logger.error(
                "下单失败: %s %s %s %.4f @ %.4f 错误=%s",
                exchange_name, side, symbol, amount, price, e, exc_info=True,
            )
            raise

    async def cancel_order(self, exchange_name: str, order_id: str) -> None:
        """
        取消指定交易所的订单

        Args:
            exchange_name: 交易所名称
            order_id: 订单ID
        """
        exchange = self._get_exchange(exchange_name)
        if exchange is None:
            return

        try:
            await exchange.cancel_order(order_id)
            logger.info("已取消订单: %s %s", exchange_name, order_id)
        except Exception as e:
            logger.warning("取消订单失败: %s %s %s", exchange_name, order_id, e)

    async def get_order_status(
        self, exchange_name: str, order_id: str
    ) -> Dict[str, Any]:
        """
        查询订单状态

        Args:
            exchange_name: 交易所名称
            order_id: 订单ID

        Returns:
            订单状态字典，包含 status, filled, average 等字段
        """
        exchange = self._get_exchange(exchange_name)
        if exchange is None:
            return {"status": "unknown"}

        try:
            order = await exchange.fetch_order(order_id)
            return {
                "status": order.get("status", "unknown"),
                "filled": order.get("filled", 0),
                "remaining": order.get("remaining", 0),
                "average": order.get("average", 0),
            }
        except Exception as e:
            logger.error("查询订单状态失败: %s %s %s",
                         exchange_name, order_id, e, exc_info=True)
            return {"status": "unknown"}

    def get_trade_history(self, limit: int = 50) -> List[TradeResult]:
        """
        获取交易历史记录

        优先从数据库查询（持久化层），数据库不可用时回退到内存缓存。
        数据库返回的字典 key 与 TradeResult 字段名一致，paper_trade 已转回 bool。

        Args:
            limit: 返回的最大记录数

        Returns:
            交易结果列表（按时间倒序）
        """
        if self.database:
            rows = self.database.get_trades(limit)
            return [TradeResult(**row) for row in rows]
        return self.trade_history[-limit:][::-1]

    async def close(self) -> None:
        """关闭所有交易所连接，释放资源"""
        for exchange in self._exchange_instances.values():
            try:
                await exchange.close()
            except Exception as e:
                logger.warning("关闭交易所连接失败: %s", e)
        self._exchange_instances.clear()
        logger.info("交易执行器已关闭")
