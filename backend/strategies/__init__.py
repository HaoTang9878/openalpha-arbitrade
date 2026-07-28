"""
策略模块包

提供可插拔的交易策略框架：
- BaseStrategy: 策略抽象基类
- StrategyRegistry: 策略注册中心
- StrategyOrchestrator: 策略调度器
- GridStrategy: 网格交易机器人
- DcaStrategy: DCA 定投机器人
- TriangularStrategy: 三角套利策略
"""

from .base import BaseStrategy, StrategySignal, StrategyStatus
from .registry import StrategyRegistry
from .orchestrator import StrategyOrchestrator
from .grid import GridStrategy
from .dca import DcaStrategy
from .triangular import TriangularStrategy

__all__ = [
    "BaseStrategy",
    "StrategySignal",
    "StrategyStatus",
    "StrategyRegistry",
    "StrategyOrchestrator",
    "GridStrategy",
    "DcaStrategy",
    "TriangularStrategy",
]
