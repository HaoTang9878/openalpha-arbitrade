"""
回测模块包

提供历史数据采集和策略回测功能：
- HistoryCollector: K 线历史数据采集器
- BacktestEngine: 回测引擎核心
- BacktestResult: 回测结果数据结构
"""

from .collector import HistoryCollector, SUPPORTED_TIMEFRAMES
from .engine import BacktestEngine, BacktestResult, BacktestTrade

__all__ = [
    "HistoryCollector",
    "BacktestEngine",
    "BacktestResult",
    "BacktestTrade",
    "SUPPORTED_TIMEFRAMES",
]
