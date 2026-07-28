"""
SQLite 持久化层单元测试

覆盖 backend/database.py 的核心方法：
- Database.__init__() — 初始化和建表
- save_trade() — 保存交易
- get_trades() — 查询交易历史
- save_opportunities() — 批量保存机会
- get_daily_pnl() — 当日盈亏
- get_trade_count() — 交易计数
- close() — 关闭连接
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from backend.database import Database
from backend.models import (
    ArbitrageOpportunity,
    OrderStatus,
    RiskLevel,
    TradeResult,
)


# ----------------------------------------------------------------------------
# __init__() 初始化与建表测试
# ----------------------------------------------------------------------------
class TestDatabaseInit:
    """Database.__init__() 初始化和建表测试"""

    def test_init_creates_db_file(self, tmp_path):
        """初始化创建数据库文件"""
        db_path = str(tmp_path / "test.db")
        db = Database(db_path)
        assert Path(db_path).exists()
        db.close()

    def test_init_creates_data_directory(self, tmp_path):
        """初始化自动创建数据目录"""
        db_path = str(tmp_path / "nested" / "deep" / "test.db")
        db = Database(db_path)
        assert Path(db_path).parent.exists()
        db.close()

    def test_init_creates_tables(self, tmp_db):
        """初始化创建 trades 和 opportunities 表"""
        cursor = tmp_db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row["name"] for row in cursor.fetchall()}
        assert "trades" in tables
        assert "opportunities" in tables

    def test_init_creates_indexes(self, tmp_db):
        """初始化创建索引"""
        cursor = tmp_db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        indexes = {row["name"] for row in cursor.fetchall()}
        assert "idx_trades_created_at" in indexes
        assert "idx_opps_created_at" in indexes

    def test_init_idempotent(self, tmp_path):
        """重复初始化不报错（IF NOT EXISTS）"""
        db_path = str(tmp_path / "test.db")
        db1 = Database(db_path)
        db1.close()
        # 再次初始化同一文件
        db2 = Database(db_path)
        db2.close()


# ----------------------------------------------------------------------------
# save_trade() / get_trades() 交易保存与查询测试
# ----------------------------------------------------------------------------
class TestSaveAndGetTrade:
    """save_trade() 和 get_trades() 测试"""

    def test_save_and_get_trade(self, tmp_db, sample_trade_result):
        """保存并查询交易记录"""
        tmp_db.save_trade(sample_trade_result)
        trades = tmp_db.get_trades(limit=10)
        assert len(trades) == 1
        trade = trades[0]
        assert trade["id"] == sample_trade_result.id
        assert trade["symbol"] == sample_trade_result.symbol
        assert trade["buy_exchange"] == sample_trade_result.buy_exchange
        assert trade["sell_exchange"] == sample_trade_result.sell_exchange
        assert trade["buy_price"] == sample_trade_result.buy_price
        assert trade["sell_price"] == sample_trade_result.sell_price
        assert trade["amount"] == sample_trade_result.amount
        assert trade["status"] == sample_trade_result.status.value
        assert trade["profit"] == sample_trade_result.profit
        assert trade["paper_trade"] is True
        assert trade["timestamp"] == sample_trade_result.timestamp

    def test_save_trade_preserves_order_ids(self, tmp_db, sample_trade_result):
        """保存交易保留订单 ID"""
        tmp_db.save_trade(sample_trade_result)
        trade = tmp_db.get_trades(1)[0]
        assert trade["buy_order_id"] == sample_trade_result.buy_order_id
        assert trade["sell_order_id"] == sample_trade_result.sell_order_id

    def test_save_trade_replace_on_duplicate_id(self, tmp_db, sample_trade_result):
        """相同 ID 的交易被替换（INSERT OR REPLACE）"""
        tmp_db.save_trade(sample_trade_result)
        # 修改后再次保存（相同 ID）
        updated = sample_trade_result.model_copy(update={"profit": 999.0})
        tmp_db.save_trade(updated)
        trades = tmp_db.get_trades(10)
        assert len(trades) == 1
        assert trades[0]["profit"] == 999.0

    def test_get_trades_empty(self, tmp_db):
        """空数据库查询返回空列表"""
        assert tmp_db.get_trades() == []

    def test_get_trades_limit(self, tmp_db):
        """get_trades 限制返回数量"""
        for i in range(5):
            trade = TradeResult(
                id=f"trade_{i}",
                symbol="BTC/USDT",
                buy_exchange="binance",
                sell_exchange="okx",
                buy_price=95000.0,
                sell_price=95100.0,
                amount=0.01,
                status=OrderStatus.FILLED,
                profit=0.5,
                paper_trade=True,
                timestamp="2026-07-28 01:00:00",
            )
            tmp_db.save_trade(trade)
        trades = tmp_db.get_trades(limit=3)
        assert len(trades) == 3

    def test_get_trades_ordered_by_created_at_desc(self, tmp_db):
        """get_trades 按创建时间倒序返回"""
        trade1 = TradeResult(
            id="first", symbol="BTC/USDT", buy_exchange="binance",
            sell_exchange="okx", buy_price=95000.0, sell_price=95100.0,
            amount=0.01, status=OrderStatus.FILLED, profit=1.0,
            paper_trade=True, timestamp="2026-07-28 01:00:00",
        )
        tmp_db.save_trade(trade1)
        # 确保有微小时间差
        import time
        time.sleep(0.01)
        trade2 = TradeResult(
            id="second", symbol="ETH/USDT", buy_exchange="binance",
            sell_exchange="okx", buy_price=3200.0, sell_price=3210.0,
            amount=0.1, status=OrderStatus.FILLED, profit=0.8,
            paper_trade=True, timestamp="2026-07-28 02:00:00",
        )
        tmp_db.save_trade(trade2)
        trades = tmp_db.get_trades(limit=10)
        # 最新的在前
        assert trades[0]["id"] == "second"
        assert trades[1]["id"] == "first"

    def test_save_trade_with_error_field(self, tmp_db):
        """保存带错误信息的失败交易"""
        trade = TradeResult(
            id="failed_trade", symbol="BTC/USDT",
            buy_exchange="binance", sell_exchange="okx",
            amount=0.01, status=OrderStatus.FAILED,
            error="余额不足", paper_trade=False,
            timestamp="2026-07-28 01:00:00",
        )
        tmp_db.save_trade(trade)
        result = tmp_db.get_trades(1)[0]
        assert result["error"] == "余额不足"
        assert result["status"] == OrderStatus.FAILED.value
        assert result["paper_trade"] is False


# ----------------------------------------------------------------------------
# save_opportunities() 批量保存机会测试
# ----------------------------------------------------------------------------
class TestSaveOpportunities:
    """save_opportunities() 批量保存机会测试"""

    def test_save_opportunities(self, tmp_db, sample_opportunity):
        """批量保存套利机会"""
        opportunities = [
            sample_opportunity,
            sample_opportunity.model_copy(update={"symbol": "ETH/USDT"}),
        ]
        tmp_db.save_opportunities(opportunities)
        # 验证写入数量
        cursor = tmp_db._conn.execute("SELECT COUNT(*) AS cnt FROM opportunities")
        assert cursor.fetchone()["cnt"] == 2

    def test_save_opportunities_empty_list(self, tmp_db):
        """空列表不写入"""
        tmp_db.save_opportunities([])
        cursor = tmp_db._conn.execute("SELECT COUNT(*) AS cnt FROM opportunities")
        assert cursor.fetchone()["cnt"] == 0

    def test_save_opportunities_preserves_fields(self, tmp_db, sample_opportunity):
        """保存机会保留所有字段"""
        tmp_db.save_opportunities([sample_opportunity])
        cursor = tmp_db._conn.execute(
            "SELECT * FROM opportunities WHERE symbol = ?", (sample_opportunity.symbol,)
        )
        row = cursor.fetchone()
        assert row["symbol"] == sample_opportunity.symbol
        assert row["buy_exchange"] == sample_opportunity.buy_exchange
        assert row["sell_exchange"] == sample_opportunity.sell_exchange
        assert row["buy_price"] == sample_opportunity.buy_price
        assert row["sell_price"] == sample_opportunity.sell_price
        assert row["spread_percent"] == sample_opportunity.spread_percent
        assert row["net_profit_rate"] == sample_opportunity.net_profit_rate
        assert row["estimated_profit"] == sample_opportunity.estimated_profit
        assert row["risk_level"] == sample_opportunity.risk_level.value
        assert row["timestamp"] == sample_opportunity.timestamp

    def test_save_opportunities_multiple_batches(self, tmp_db, sample_opportunity):
        """多次批量保存累积"""
        for i in range(3):
            tmp_db.save_opportunities([sample_opportunity])
        cursor = tmp_db._conn.execute("SELECT COUNT(*) AS cnt FROM opportunities")
        assert cursor.fetchone()["cnt"] == 3


# ----------------------------------------------------------------------------
# get_daily_pnl() 当日盈亏测试
# ----------------------------------------------------------------------------
class TestGetDailyPnl:
    """get_daily_pnl() 当日盈亏计算测试"""

    def test_get_daily_pnl_empty(self, tmp_db):
        """空数据库当日盈亏为 0"""
        assert tmp_db.get_daily_pnl() == 0.0

    def test_get_daily_pnl_today(self, tmp_db):
        """计算当日交易盈亏"""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        trades = [
            TradeResult(
                id="t1", symbol="BTC/USDT", buy_exchange="binance",
                sell_exchange="okx", buy_price=95000.0, sell_price=95100.0,
                amount=0.01, status=OrderStatus.FILLED, profit=1.5,
                paper_trade=True, timestamp=f"{today} 01:00:00",
            ),
            TradeResult(
                id="t2", symbol="ETH/USDT", buy_exchange="binance",
                sell_exchange="okx", buy_price=3200.0, sell_price=3210.0,
                amount=0.1, status=OrderStatus.FILLED, profit=0.8,
                paper_trade=True, timestamp=f"{today} 02:00:00",
            ),
        ]
        for t in trades:
            tmp_db.save_trade(t)
        assert tmp_db.get_daily_pnl() == pytest.approx(2.3)

    def test_get_daily_pnl_excludes_other_days(self, tmp_db):
        """当日盈亏排除其他日期的交易"""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        yesterday = "2020-01-01"
        tmp_db.save_trade(TradeResult(
            id="today", symbol="BTC/USDT", buy_exchange="binance",
            sell_exchange="okx", buy_price=95000.0, sell_price=95100.0,
            amount=0.01, status=OrderStatus.FILLED, profit=5.0,
            paper_trade=True, timestamp=f"{today} 01:00:00",
        ))
        tmp_db.save_trade(TradeResult(
            id="yesterday", symbol="BTC/USDT", buy_exchange="binance",
            sell_exchange="okx", buy_price=95000.0, sell_price=95100.0,
            amount=0.01, status=OrderStatus.FILLED, profit=100.0,
            paper_trade=True, timestamp=f"{yesterday} 01:00:00",
        ))
        assert tmp_db.get_daily_pnl() == pytest.approx(5.0)

    def test_get_daily_pnl_negative(self, tmp_db):
        """当日亏损计算为负值"""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        tmp_db.save_trade(TradeResult(
            id="loss", symbol="BTC/USDT", buy_exchange="binance",
            sell_exchange="okx", buy_price=95100.0, sell_price=95000.0,
            amount=0.01, status=OrderStatus.FILLED, profit=-2.5,
            paper_trade=True, timestamp=f"{today} 01:00:00",
        ))
        assert tmp_db.get_daily_pnl() == pytest.approx(-2.5)


# ----------------------------------------------------------------------------
# get_trade_count() 交易计数测试
# ----------------------------------------------------------------------------
class TestGetTradeCount:
    """get_trade_count() 交易计数测试"""

    def test_get_trade_count_empty(self, tmp_db):
        """空数据库交易计数为 0"""
        assert tmp_db.get_trade_count() == 0

    def test_get_trade_count_after_saves(self, tmp_db, sample_trade_result):
        """保存后计数正确"""
        for i in range(3):
            tmp_db.save_trade(sample_trade_result.model_copy(update={"id": f"t{i}"}))
        assert tmp_db.get_trade_count() == 3

    def test_get_trade_count_dedup_by_id(self, tmp_db, sample_trade_result):
        """相同 ID 不重复计数（INSERT OR REPLACE）"""
        tmp_db.save_trade(sample_trade_result)
        tmp_db.save_trade(sample_trade_result)  # 相同 ID
        assert tmp_db.get_trade_count() == 1


# ----------------------------------------------------------------------------
# close() 关闭连接测试
# ----------------------------------------------------------------------------
class TestDatabaseClose:
    """close() 关闭连接测试"""

    def test_close_releases_connection(self, tmp_path):
        """关闭后连接释放"""
        db_path = str(tmp_path / "test.db")
        db = Database(db_path)
        db.close()
        # 关闭后再次操作应失败
        with pytest.raises(sqlite3.ProgrammingError):
            db._conn.execute("SELECT 1")

    def test_close_idempotent(self, tmp_path):
        """重复关闭不抛异常"""
        db_path = str(tmp_path / "test.db")
        db = Database(db_path)
        db.close()
        db.close()  # 不应抛异常


# ----------------------------------------------------------------------------
# 并发安全测试
# ----------------------------------------------------------------------------
class TestDatabaseConcurrency:
    """线程安全测试（threading.Lock 串行化）"""

    def test_concurrent_saves_thread_safe(self, tmp_path):
        """多线程并发保存不报错"""
        import threading

        db_path = str(tmp_path / "test.db")
        db = Database(db_path)
        errors = []

        def save_trades(thread_id):
            try:
                for i in range(10):
                    db.save_trade(TradeResult(
                        id=f"t{thread_id}_{i}", symbol="BTC/USDT",
                        buy_exchange="binance", sell_exchange="okx",
                        buy_price=95000.0, sell_price=95100.0,
                        amount=0.01, status=OrderStatus.FILLED,
                        profit=0.5, paper_trade=True,
                        timestamp="2026-07-28 01:00:00",
                    ))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=save_trades, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert db.get_trade_count() == 40
        db.close()
