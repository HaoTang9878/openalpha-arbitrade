"""
历史数据采集模块

使用 CCXT 的 fetch_ohlcv 接口下载交易所的 K 线（OHLCV）历史数据，
存储到 SQLite 数据库供回测引擎使用。

支持的功能：
- 按交易对、交易所、时间范围下载 K 线
- 增量更新（只下载缺失的最新数据）
- 多时间周期支持（1m/5m/15m/1h/4h/1d）

使用方法：
    collector = HistoryCollector(database)
    await collector.download_klines("binance", "BTC/USDT", "1h", days=30)
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import ccxt.async_support as ccxt

from ..database import Database

logger = logging.getLogger(__name__)

# CCXT fetch_ohlcv 单次最大返回条数
MAX_OHLCV_LIMIT = 1000

# 支持的时间周期
SUPPORTED_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]

# 时间周期 → 毫秒
TIMEFRAME_MS = {
    "1m": 60 * 1000,
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


class HistoryCollector:
    """
    历史数据采集器

    从交易所下载 K 线数据并存储到数据库。
    """

    def __init__(self, database: Database) -> None:
        """
        初始化采集器

        Args:
            database: 数据库实例（用于存储 K 线数据）
        """
        self.database = database
        self._init_klines_table()

    def _init_klines_table(self) -> None:
        """创建 K 线数据表（如果不存在）"""
        try:
            with self.database._lock:
                self.database._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS klines (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        exchange TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        timestamp INTEGER NOT NULL,
                        open REAL NOT NULL,
                        high REAL NOT NULL,
                        low REAL NOT NULL,
                        close REAL NOT NULL,
                        volume REAL NOT NULL,
                        UNIQUE(exchange, symbol, timeframe, timestamp)
                    )
                    """
                )
                # 索引加速查询
                self.database._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_klines_lookup "
                    "ON klines(exchange, symbol, timeframe, timestamp)"
                )
            logger.info("K 线数据表已就绪")
        except Exception as e:
            logger.error("创建 K 线表失败: %s", e)

    async def download_klines(
        self,
        exchange_name: str,
        symbol: str,
        timeframe: str = "1h",
        days: int = 30,
    ) -> int:
        """
        下载指定交易对的 K 线历史数据

        Args:
            exchange_name: 交易所名称（如 binance）
            symbol: 交易对（如 BTC/USDT）
            timeframe: 时间周期（如 1h）
            days: 下载最近多少天的数据

        Returns:
            下载的 K 线条数
        """
        if timeframe not in SUPPORTED_TIMEFRAMES:
            logger.error("不支持的时间周期: %s", timeframe)
            return 0

        exchange = None
        total_count = 0

        try:
            exchange_class = getattr(ccxt, exchange_name, None)
            if exchange_class is None:
                logger.error("不支持的交易所: %s", exchange_name)
                return 0

            exchange = exchange_class({"enableRateLimit": True, "timeout": 10000})
            await exchange.load_markets()

            if symbol not in exchange.markets:
                logger.warning("%s 不支持 %s", exchange_name, symbol)
                return 0

            # 计算时间范围
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - days * 24 * 60 * 60 * 1000
            tf_ms = TIMEFRAME_MS[timeframe]

            logger.info(
                "开始下载 %s %s %s K线（最近 %d 天）",
                exchange_name, symbol, timeframe, days,
            )

            # 分批下载
            current_ms = start_ms
            batch_count = 0

            while current_ms < now_ms:
                try:
                    ohlcv = await exchange.fetch_ohlcv(
                        symbol, timeframe, since=current_ms, limit=MAX_OHLCV_LIMIT
                    )
                except Exception as e:
                    logger.warning("下载批次失败: %s", e)
                    break

                if not ohlcv:
                    break

                # 存储到数据库
                self._save_klines(exchange_name, symbol, timeframe, ohlcv)
                total_count += len(ohlcv)
                batch_count += 1

                # 移动到下一批
                current_ms = ohlcv[-1][0] + tf_ms

                # 避免触发限流
                await asyncio.sleep(0.2)

                # 已下载到最新数据
                if len(ohlcv) < MAX_OHLCV_LIMIT:
                    break

            logger.info(
                "下载完成: %s %s %s 共 %d 条（%d 批）",
                exchange_name, symbol, timeframe, total_count, batch_count,
            )

        except Exception as e:
            logger.error("下载 K 线失败: %s", e, exc_info=True)
        finally:
            if exchange:
                await exchange.close()

        return total_count

    def _save_klines(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        ohlcv: List[List[Any]],
    ) -> None:
        """将 K 线数据批量写入数据库（INSERT OR IGNORE 去重）"""
        rows = [
            (exchange, symbol, timeframe, int(c[0]),
             float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5]))
            for c in ohlcv
        ]
        try:
            with self.database._lock:
                self.database._conn.executemany(
                    """
                    INSERT OR IGNORE INTO klines
                        (exchange, symbol, timeframe, timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
        except Exception as e:
            logger.error("保存 K 线失败: %s", e)

    def get_klines(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        查询 K 线数据

        Args:
            exchange: 交易所名称
            symbol: 交易对
            timeframe: 时间周期
            limit: 返回最大条数

        Returns:
            K 线字典列表 [{timestamp, open, high, low, close, volume}]
        """
        try:
            with self.database._lock:
                cursor = self.database._conn.execute(
                    """
                    SELECT timestamp, open, high, low, close, volume
                    FROM klines
                    WHERE exchange = ? AND symbol = ? AND timeframe = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (exchange, symbol, timeframe, limit),
                )
                rows = cursor.fetchall()
        except Exception as e:
            logger.error("查询 K 线失败: %s", e)
            return []

        # 按时间正序返回
        result = []
        for row in reversed(rows):
            result.append({
                "timestamp": row["timestamp"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            })
        return result

    def get_kline_count(
        self, exchange: str, symbol: str, timeframe: str
    ) -> int:
        """查询已存储的 K 线条数"""
        try:
            with self.database._lock:
                cursor = self.database._conn.execute(
                    "SELECT COUNT(*) AS cnt FROM klines "
                    "WHERE exchange = ? AND symbol = ? AND timeframe = ?",
                    (exchange, symbol, timeframe),
                )
                row = cursor.fetchone()
                return int(row["cnt"]) if row else 0
        except Exception:
            return 0
