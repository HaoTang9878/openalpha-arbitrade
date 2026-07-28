"""
SQLite 持久化层 — 交易历史与套利机会记录

使用 Python 标准库 sqlite3，无需额外依赖。
数据库文件路径：data/arbitrage.db（Docker 挂载到宿主机 ./data/arbitrage.db）

表结构：
- trades: 交易历史记录
- opportunities: 套利机会快照（每次检测到的机会批量写入）

并发安全说明：
- 使用 check_same_thread=False 允许 FastAPI 异步框架多线程访问
- 启用 WAL 模式提升并发读写性能
- 所有写操作通过 threading.Lock 串行化，避免 "database is locked" 错误
"""

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import ArbitrageOpportunity, TradeResult

logger = logging.getLogger(__name__)

# 默认数据库文件路径：项目根目录 / data / arbitrage.db
DEFAULT_DB_PATH = str(Path(__file__).parent.parent / "data" / "arbitrage.db")


class Database:
    """
    SQLite 持久化层

    封装交易历史与套利机会的增删查改操作，提供线程安全的并发访问。

    使用方法：
        db = Database("data/arbitrage.db")
        db.save_trade(trade_result)
        trades = db.get_trades(limit=50)
        db.close()
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        """
        初始化数据库连接并自动建表

        Args:
            db_path: 数据库文件路径，默认为 data/arbitrage.db
        """
        self.db_path = db_path
        self._lock = threading.Lock()

        # 确保数据目录存在
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        # check_same_thread=False 允许 FastAPI 异步框架多线程访问
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level=None,  # 自动提交模式
        )
        # 让查询结果按列名访问
        self._conn.row_factory = sqlite3.Row

        # 启用 WAL 模式提升并发读写性能
        try:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
        except sqlite3.Error as e:
            logger.warning("设置 SQLite PRAGMA 失败（忽略）: %s", e)

        self._init_db()
        logger.info("SQLite 数据库已初始化: %s", db_path)

    def _init_db(self) -> None:
        """创建表（IF NOT EXISTS）"""
        with self._lock:
            cursor = self._conn.cursor()
            # 交易历史表
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    buy_exchange TEXT NOT NULL,
                    sell_exchange TEXT NOT NULL,
                    buy_price REAL NOT NULL,
                    sell_price REAL NOT NULL,
                    amount REAL NOT NULL,
                    buy_order_id TEXT,
                    sell_order_id TEXT,
                    status TEXT NOT NULL,
                    profit REAL NOT NULL,
                    error TEXT,
                    paper_trade INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            # 套利机会快照表
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS opportunities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    buy_exchange TEXT NOT NULL,
                    sell_exchange TEXT NOT NULL,
                    buy_price REAL NOT NULL,
                    sell_price REAL NOT NULL,
                    spread_percent REAL NOT NULL,
                    net_profit_rate REAL NOT NULL,
                    estimated_profit REAL NOT NULL,
                    risk_level TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            # 索引：按创建时间倒序查询交易历史
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_trades_created_at "
                "ON trades(created_at DESC);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_opps_created_at "
                "ON opportunities(created_at DESC);"
            )

    def save_trade(self, trade: TradeResult) -> None:
        """
        保存单笔交易（INSERT OR REPLACE）

        Args:
            trade: 交易结果对象
        """
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO trades (
                        id, symbol, buy_exchange, sell_exchange,
                        buy_price, sell_price, amount,
                        buy_order_id, sell_order_id, status,
                        profit, error, paper_trade, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade.id,
                        trade.symbol,
                        trade.buy_exchange,
                        trade.sell_exchange,
                        trade.buy_price,
                        trade.sell_price,
                        trade.amount,
                        trade.buy_order_id,
                        trade.sell_order_id,
                        trade.status.value if hasattr(trade.status, "value") else str(trade.status),
                        trade.profit,
                        trade.error,
                        1 if trade.paper_trade else 0,
                        trade.timestamp,
                    ),
                )
                logger.debug("已保存交易记录: id=%s symbol=%s", trade.id, trade.symbol)
            except sqlite3.Error as e:
                logger.error("保存交易记录失败: %s", e, exc_info=True)

    def save_opportunities(
        self, opportunities: List[ArbitrageOpportunity]
    ) -> None:
        """
        批量保存套利机会快照

        Args:
            opportunities: 套利机会列表
        """
        if not opportunities:
            return

        rows = []
        for op in opportunities:
            rows.append(
                (
                    op.symbol,
                    op.buy_exchange,
                    op.sell_exchange,
                    op.buy_price,
                    op.sell_price,
                    op.spread_percent,
                    op.net_profit_rate,
                    op.estimated_profit,
                    op.risk_level.value if hasattr(op.risk_level, "value") else str(op.risk_level),
                    op.timestamp,
                )
            )

        with self._lock:
            try:
                self._conn.executemany(
                    """
                    INSERT INTO opportunities (
                        symbol, buy_exchange, sell_exchange,
                        buy_price, sell_price, spread_percent,
                        net_profit_rate, estimated_profit, risk_level, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                logger.debug("已批量保存 %d 条套利机会", len(opportunities))
            except sqlite3.Error as e:
                logger.error("批量保存套利机会失败: %s", e, exc_info=True)

    def get_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        查询交易历史（按 created_at DESC）

        Args:
            limit: 返回的最大记录数

        Returns:
            交易记录字典列表，key 与 TradeResult 字段名一致，
            paper_trade 已从 int 转回 bool
        """
        with self._lock:
            try:
                cursor = self._conn.execute(
                    """
                    SELECT id, symbol, buy_exchange, sell_exchange,
                           buy_price, sell_price, amount,
                           buy_order_id, sell_order_id, status,
                           profit, error, paper_trade, timestamp
                    FROM trades
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
            except sqlite3.Error as e:
                logger.error("查询交易历史失败: %s", e, exc_info=True)
                return []

        result: List[Dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "id": row["id"],
                    "symbol": row["symbol"],
                    "buy_exchange": row["buy_exchange"],
                    "sell_exchange": row["sell_exchange"],
                    "buy_price": row["buy_price"],
                    "sell_price": row["sell_price"],
                    "amount": row["amount"],
                    "buy_order_id": row["buy_order_id"],
                    "sell_order_id": row["sell_order_id"],
                    "status": row["status"],
                    "profit": row["profit"],
                    "error": row["error"],
                    "paper_trade": bool(row["paper_trade"]),
                    "timestamp": row["timestamp"],
                }
            )
        return result

    def get_trade_count(self) -> int:
        """
        查询交易总数

        Returns:
            数据库中交易记录的总条数
        """
        with self._lock:
            try:
                cursor = self._conn.execute("SELECT COUNT(*) AS cnt FROM trades")
                row = cursor.fetchone()
                return int(row["cnt"]) if row else 0
            except sqlite3.Error as e:
                logger.error("查询交易总数失败: %s", e, exc_info=True)
                return 0

    def get_daily_pnl(self, date_str: Optional[str] = None) -> float:
        """
        指定日期的盈亏汇总

        汇总某天（按 timestamp 字段前 10 位匹配 YYYY-MM-DD）所有交易的
        profit 字段之和。未指定日期时默认取当天（UTC+8）。

        Args:
            date_str: 日期字符串（YYYY-MM-DD），可选

        Returns:
            指定日期的盈亏总额（USDT）
        """
        target = date_str or datetime.utcnow().strftime("%Y-%m-%d")
        with self._lock:
            try:
                cursor = self._conn.execute(
                    """
                    SELECT COALESCE(SUM(profit), 0) AS pnl
                    FROM trades
                    WHERE substr(timestamp, 1, 10) = ?
                    """,
                    (target,),
                )
                row = cursor.fetchone()
                return float(row["pnl"]) if row else 0.0
            except sqlite3.Error as e:
                logger.error("查询当日盈亏失败: %s", e, exc_info=True)
                return 0.0

    def get_daily_trades(self, date_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        查询指定日期的所有交易记录

        Args:
            date_str: 日期字符串（YYYY-MM-DD），默认当天

        Returns:
            交易记录字典列表
        """
        target = date_str or datetime.utcnow().strftime("%Y-%m-%d")
        with self._lock:
            try:
                cursor = self._conn.execute(
                    """
                    SELECT id, symbol, buy_exchange, sell_exchange,
                           buy_price, sell_price, amount, status,
                           profit, paper_trade, timestamp
                    FROM trades
                    WHERE substr(timestamp, 1, 10) = ?
                    ORDER BY created_at DESC
                    """,
                    (target,),
                )
                rows = cursor.fetchall()
            except sqlite3.Error as e:
                logger.error("查询当日交易失败: %s", e, exc_info=True)
                return []
        return [dict(row) for row in rows]

    def get_daily_opportunities(
        self, date_str: Optional[str] = None, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        查询指定日期的套利机会快照

        Args:
            date_str: 日期字符串（YYYY-MM-DD），默认当天
            limit: 返回最大条数

        Returns:
            机会记录字典列表
        """
        target = date_str or datetime.utcnow().strftime("%Y-%m-%d")
        with self._lock:
            try:
                cursor = self._conn.execute(
                    """
                    SELECT symbol, buy_exchange, sell_exchange,
                           buy_price, sell_price, spread_percent,
                           net_profit_rate, estimated_profit, risk_level,
                           timestamp, created_at
                    FROM opportunities
                    WHERE substr(created_at, 1, 10) = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (target, limit),
                )
                rows = cursor.fetchall()
            except sqlite3.Error as e:
                logger.error("查询当日机会失败: %s", e, exc_info=True)
                return []
        return [dict(row) for row in rows]

    def get_opportunity_count(self, date_str: Optional[str] = None) -> int:
        """
        查询指定日期的机会快照总数

        Args:
            date_str: 日期字符串（YYYY-MM-DD），默认当天

        Returns:
            机会记录总数
        """
        target = date_str or datetime.utcnow().strftime("%Y-%m-%d")
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "SELECT COUNT(*) AS cnt FROM opportunities "
                    "WHERE substr(created_at, 1, 10) = ?",
                    (target,),
                )
                row = cursor.fetchone()
                return int(row["cnt"]) if row else 0
            except sqlite3.Error as e:
                logger.error("查询机会总数失败: %s", e, exc_info=True)
                return 0

    def get_daily_report(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """
        生成指定日期的每日报告聚合数据

        汇总当日机会检测与交易执行的统计信息，包括：
        - 机会总数、唯一交易对数、唯一交易所对数
        - 交易笔数、盈亏、胜率
        - 价差分布、Top10 机会、频次统计

        Args:
            date_str: 日期字符串（YYYY-MM-DD），默认当天

        Returns:
            每日报告字典
        """
        target = date_str or datetime.utcnow().strftime("%Y-%m-%d")
        opps = self.get_daily_opportunities(target, limit=5000)
        trades = self.get_daily_trades(target)

        # 唯一交易对与交易所对
        symbols_set = {o["symbol"] for o in opps}
        pairs_set = {
            f"{o['buy_exchange']}→{o['sell_exchange']}" for o in opps
        }

        # 价差分布
        spread_dist = {"<0.1%": 0, "0.1-0.5%": 0, "0.5-1%": 0, ">1%": 0}
        for o in opps:
            sp = o.get("spread_percent", 0) * 100
            if sp < 0.1:
                spread_dist["<0.1%"] += 1
            elif sp < 0.5:
                spread_dist["0.1-0.5%"] += 1
            elif sp < 1:
                spread_dist["0.5-1%"] += 1
            else:
                spread_dist[">1%"] += 1

        # Top10 最大价差机会
        top_opps = sorted(
            opps, key=lambda x: x.get("spread_percent", 0), reverse=True
        )[:10]

        # 交易所对频次
        pair_freq: Dict[str, int] = {}
        for o in opps:
            key = f"{o['buy_exchange']}→{o['sell_exchange']}"
            pair_freq[key] = pair_freq.get(key, 0) + 1

        # 交易对频次
        sym_freq: Dict[str, int] = {}
        for o in opps:
            sym_freq[o["symbol"]] = sym_freq.get(o["symbol"], 0) + 1

        # 交易统计
        total_profit = sum(t.get("profit", 0) for t in trades)
        filled = [t for t in trades if t.get("status") == "filled"]
        win = [t for t in filled if t.get("profit", 0) > 0]
        win_rate = len(win) / len(filled) if filled else 0.0

        return {
            "date": target,
            "total_opportunities": len(opps),
            "unique_symbols": len(symbols_set),
            "unique_exchange_pairs": len(pairs_set),
            "total_trades": len(trades),
            "total_profit": round(total_profit, 4),
            "win_rate": round(win_rate, 4),
            "spread_distribution": spread_dist,
            "top_opportunities": top_opps,
            "exchange_pair_frequency": pair_freq,
            "symbol_frequency": sym_freq,
        }

    def close(self) -> None:
        """关闭数据库连接，释放资源"""
        with self._lock:
            try:
                self._conn.close()
                logger.info("SQLite 数据库连接已关闭")
            except sqlite3.Error as e:
                logger.warning("关闭数据库连接失败: %s", e)
