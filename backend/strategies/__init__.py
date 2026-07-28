"""
策略模块包 — 聚焦纯现货套利

本模块严格遵循产品定位（详见 docs/PURPOSE_AND_BENCHMARK.md）：
- ✅ 跨所套利（cross-exchange spot arbitrage）
- ✅ 三角套利（triangular arbitrage，同所内 A→B→C→A）
- ⚠️ 网格/DCA 等"未来扩展"策略（不属于纯套利，仅供研究参考）

核心策略：
- TriangularStrategy：三角套利（唯一默认启用的非内置策略）
- GridStrategy, DcaStrategy：标记为 experimental（不在主推路径）

说明：
- 跨所套利的核心检测逻辑在 backend/arbitrage.py（主入口），
  不在本策略框架内，因为它是产品的核心算法而非"可插拔策略"。
- 本策略框架保留是为未来扩展三角套利等更多套利变种。
"""

from .base import BaseStrategy, StrategySignal, StrategyStatus
from .registry import StrategyRegistry
from .orchestrator import StrategyOrchestrator
from .triangular import TriangularStrategy

# 以下为 experimental 策略（非纯套利，仅供研究参考）
from .grid import GridStrategy
from .dca import DcaStrategy

__all__ = [
    "BaseStrategy",
    "StrategySignal",
    "StrategyStatus",
    "StrategyRegistry",
    "StrategyOrchestrator",
    "TriangularStrategy",
    # experimental
    "GridStrategy",
    "DcaStrategy",
]
