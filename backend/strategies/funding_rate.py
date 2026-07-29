"""
资金费率套利策略模块

合约 vs 现货对冲，赚取资金费率差价。
核心逻辑：
1. 当合约资金费率为正（多头付空头），做空合约 + 做多现货
2. 当合约资金费率为负（空头付多头），做多合约 + 做空现货
3. 持仓期间收取资金费率，对冲价格波动风险
4. 费率结算后平仓获利

配置参数：
    exchange: 交易所名称（需支持合约）
    symbol: 交易对（如 BTC/USDT）
    min_funding_rate: 最小资金费率阈值（默认 0.0001 = 0.01%）
    position_size: 持仓规模（USDT）
    max_holding_hours: 最大持仓时间（小时）
"""

import logging
import time
from typing import Any, Dict, List

from .base import BaseStrategy, StrategySignal

logger = logging.getLogger(__name__)


class FundingRateStrategy(BaseStrategy):
    """资金费率套利策略"""

    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        super().__init__(name, config)
        self.exchange = config.get("exchange", "binance")
        self.symbol = config.get("symbol", "BTC/USDT")
        self.min_funding_rate = float(config.get("min_funding_rate", 0.0001))
        self.position_size = float(config.get("position_size", 1000))
        self.max_holding_hours = int(config.get("max_holding_hours", 8))
        self._last_funding_time: float = 0
        self._position_open: bool = False
        self._position_side: str = ""  # "long_short" or "short_long"

    async def generate_signals(
        self, prices: Dict[str, Dict[str, Dict[str, Any]]]
    ) -> List[StrategySignal]:
        if self.status.value != "running":
            return []

        # 从价格快照中提取资金费率信息（需 scanner 提供）
        ticker = prices.get(self.exchange, {}).get(self.symbol)
        if not ticker:
            return []

        funding_rate = ticker.get("funding_rate", 0)
        next_funding = ticker.get("next_funding_time", 0)
        now = time.time()

        signals: List[StrategySignal] = []

        # 检查是否应该开仓
        if not self._position_open and abs(funding_rate) >= self.min_funding_rate:
            if funding_rate > 0:
                # 费率为正：做空合约 + 做多现货
                signals.append(StrategySignal(
                    strategy_name=self.name,
                    symbol=self.symbol,
                    side="sell",
                    price=ticker.get("last", 0),
                    amount=self.position_size / ticker.get("last", 1),
                    exchange=self.exchange,
                    order_type="limit",
                    reason=f"资金费率套利: 做空合约(费率{funding_rate:.4%})",
                ))
                self._position_side = "short_long"
                self._position_open = True
                self._last_funding_time = now
            else:
                # 费率为负：做多合约 + 做空现货
                signals.append(StrategySignal(
                    strategy_name=self.name,
                    symbol=self.symbol,
                    side="buy",
                    price=ticker.get("last", 0),
                    amount=self.position_size / ticker.get("last", 1),
                    exchange=self.exchange,
                    order_type="limit",
                    reason=f"资金费率套利: 做多合约(费率{funding_rate:.4%})",
                ))
                self._position_side = "long_short"
                self._position_open = True
                self._last_funding_time = now

        # 检查是否应该平仓（费率结算后或超时）
        elif self._position_open:
            holding_hours = (now - self._last_funding_time) / 3600
            if holding_hours >= self.max_holding_hours or next_funding < now:
                close_side = "buy" if self._position_side == "short_long" else "sell"
                signals.append(StrategySignal(
                    strategy_name=self.name,
                    symbol=self.symbol,
                    side=close_side,
                    price=ticker.get("last", 0),
                    amount=self.position_size / ticker.get("last", 1),
                    exchange=self.exchange,
                    order_type="market",
                    reason=f"资金费率套利平仓(持仓{holding_hours:.1f}h)",
                ))
                self._position_open = False
                self._position_side = ""

        for s in signals:
            self.record_signal(s)
        return signals

    def get_status(self) -> Dict[str, Any]:
        status = super().get_status()
        status.update({
            "exchange": self.exchange,
            "symbol": self.symbol,
            "min_funding_rate": self.min_funding_rate,
            "position_size": self.position_size,
            "position_open": self._position_open,
            "position_side": self._position_side,
        })
        return status
