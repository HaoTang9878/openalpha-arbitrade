"""
DCA 定投机器人策略模块

定期定额买入策略，价格下跌时自动加码买入，降低平均成本，
价格反弹到目标位时自动卖出获利。

核心逻辑：
1. 设定基础买入量和价格下跌加码规则
2. 每次价格下跌一定比例触发一次买入（越跌买越多）
3. 记录平均持仓成本
4. 价格反弹到目标利润率时全部卖出

配置参数：
    symbol: 交易对
    exchange: 交易所名称
    base_amount: 基础买入量（USDT）
    dip_threshold: 触发加仓的下跌幅度（如 0.02 = 跌 2%）
    max_orders: 最大加仓次数
    take_profit_pct: 止盈百分比（如 0.05 = 涨 5% 卖出）
    stop_loss_pct: 止损百分比
"""

import logging
from typing import Any, Dict, List

from .base import BaseStrategy, StrategySignal

logger = logging.getLogger(__name__)


class DcaStrategy(BaseStrategy):
    """
    DCA 定投机器人

    价格下跌分批买入，反弹到目标利润卖出。
    """

    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        """初始化 DCA 策略"""
        super().__init__(name, config)

        self.symbol = config.get("symbol", "BTC/USDT")
        self.exchange = config.get("exchange", "binance")
        self.base_amount = float(config.get("base_amount", 100))
        self.dip_threshold = float(config.get("dip_threshold", 0.02))
        self.max_orders = int(config.get("max_orders", 5))
        self.take_profit_pct = float(config.get("take_profit_pct", 0.05))
        self.stop_loss_pct = float(config.get("stop_loss_pct", 0.10))

        # 运行时状态
        self._last_buy_price: float = 0.0
        self._avg_cost: float = 0.0
        self._total_cost: float = 0.0
        self._total_amount: float = 0.0
        self._order_count = 0

    async def generate_signals(
        self,
        prices: Dict[str, Dict[str, Dict[str, Any]]],
    ) -> List[StrategySignal]:
        """
        生成 DCA 交易信号

        Args:
            prices: 价格快照

        Returns:
            交易信号列表
        """
        if self.status.value != "running":
            return []

        ticker = prices.get(self.exchange, {}).get(self.symbol)
        if not ticker or ticker.get("last", 0) <= 0:
            return []

        current_price = float(ticker["last"])
        signals: List[StrategySignal] = []

        # 首次买入
        if self._order_count == 0:
            signals.append(self._create_buy_signal(current_price, "首次定投买入"))
            return signals

        # 止盈检查
        if self._avg_cost > 0:
            profit_pct = (current_price - self._avg_cost) / self._avg_cost
            if profit_pct >= self.take_profit_pct:
                logger.info(
                    "DCA %s 止盈: 当前 %.2f 成本 %.2f 利润 %.2f%%",
                    self.name, current_price, self._avg_cost, profit_pct * 100,
                )
                signals.append(StrategySignal(
                    strategy_name=self.name,
                    symbol=self.symbol,
                    side="sell",
                    price=current_price,
                    amount=self._total_amount,
                    exchange=self.exchange,
                    order_type="market",
                    reason=f"止盈卖出 利润{profit_pct*100:.1f}%",
                ))
                self.record_signal(signals[-1])
                self._reset_position()
                return signals

            # 止损检查
            if profit_pct <= -self.stop_loss_pct:
                logger.warning(
                    "DCA %s 止损: 当前 %.2f 成本 %.2f 亏损 %.2f%%",
                    self.name, current_price, self._avg_cost, profit_pct * 100,
                )
                signals.append(StrategySignal(
                    strategy_name=self.name,
                    symbol=self.symbol,
                    side="sell",
                    price=current_price,
                    amount=self._total_amount,
                    exchange=self.exchange,
                    order_type="market",
                    reason=f"止损卖出 亏损{profit_pct*100:.1f}%",
                ))
                self.record_signal(signals[-1])
                self._reset_position()
                return signals

        # 加仓检查：价格下跌超过阈值
        if (
            self._order_count < self.max_orders
            and self._last_buy_price > 0
        ):
            dip_pct = (self._last_buy_price - current_price) / self._last_buy_price
            if dip_pct >= self.dip_threshold:
                # 越跌买越多：第 N 次买入量 = base_amount * N
                buy_usdt = self.base_amount * (self._order_count + 1)
                signals.append(self._create_buy_signal(
                    current_price,
                    f"加仓买入 第{self._order_count+1}次 跌幅{dip_pct*100:.1f}%",
                    buy_usdt,
                ))

        return signals

    def _create_buy_signal(
        self,
        price: float,
        reason: str,
        amount_usdt: float = 0,
    ) -> StrategySignal:
        """创建买入信号并更新持仓状态"""
        usdt = amount_usdt or self.base_amount
        amount = usdt / price

        # 更新平均成本
        new_total_cost = self._total_cost + usdt
        new_total_amount = self._total_amount + amount
        self._avg_cost = new_total_cost / new_total_amount if new_total_amount > 0 else 0
        self._total_cost = new_total_cost
        self._total_amount = new_total_amount
        self._last_buy_price = price
        self._order_count += 1

        signal = StrategySignal(
            strategy_name=self.name,
            symbol=self.symbol,
            side="buy",
            price=price,
            amount=amount,
            exchange=self.exchange,
            order_type="limit",
            reason=reason,
        )
        self.record_signal(signal)
        return signal

    def _reset_position(self) -> None:
        """清仓后重置持仓状态"""
        self._last_buy_price = 0.0
        self._avg_cost = 0.0
        self._total_cost = 0.0
        self._total_amount = 0.0
        self._order_count = 0

    def get_status(self) -> Dict[str, Any]:
        """获取 DCA 策略状态"""
        status = super().get_status()
        status.update({
            "symbol": self.symbol,
            "exchange": self.exchange,
            "avg_cost": round(self._avg_cost, 4),
            "total_cost": round(self._total_cost, 2),
            "total_amount": round(self._total_amount, 6),
            "order_count": self._order_count,
            "max_orders": self.max_orders,
            "last_buy_price": self._last_buy_price,
        })
        return status
