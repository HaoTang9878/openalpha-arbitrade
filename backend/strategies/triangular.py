"""
三角套利策略模块

利用同一交易所内三个交易对的汇率不一致进行套利。
例如：USDT → BTC → ETH → USDT，如果三步兑换后的 USDT 多于初始值，
则存在套利空间。

核心逻辑：
1. 枚举所有可能的三角路径（基础货币 → 中间货币 → 目标货币 → 基础货币）
2. 用各交易对的 ask/bid 计算三角兑换后的预期收益
3. 扣除三边手续费后，若净利润 > 阈值则产生套利信号
4. 信号包含三笔连续订单（买入→兑换→卖出）

配置参数：
    exchange: 交易所名称
    base_currency: 基础货币（如 USDT）
    intermediate_currencies: 中间货币列表（如 BTC, ETH）
    min_profit_pct: 最小净利润率（如 0.001 = 0.1%）
    investment_amount: 单次套利投入（USDT）
"""

import logging
from typing import Any, Dict, List

from .base import BaseStrategy, StrategySignal

logger = logging.getLogger(__name__)


class TriangularStrategy(BaseStrategy):
    """
    三角套利策略

    在同一交易所内寻找 A→B→C→A 的套利路径。
    """

    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        """初始化三角套利策略"""
        super().__init__(name, config)

        self.exchange = config.get("exchange", "binance")
        self.base_currency = config.get("base_currency", "USDT")
        self.intermediate_currencies = config.get(
            "intermediate_currencies", ["BTC", "ETH"]
        )
        self.min_profit_pct = float(config.get("min_profit_pct", 0.001))
        self.investment_amount = float(config.get("investment_amount", 100))

    async def generate_signals(
        self,
        prices: Dict[str, Dict[str, Dict[str, Any]]],
    ) -> List[StrategySignal]:
        """
        生成三角套利信号

        Args:
            prices: 价格快照

        Returns:
            交易信号列表（每个套利机会产生 3 个信号）
        """
        if self.status.value != "running":
            return []

        exchange_prices = prices.get(self.exchange, {})
        if not exchange_prices:
            return []

        signals: List[StrategySignal] = []

        # 枚举所有三角路径
        for mid_currency in self.intermediate_currencies:
            for target_currency in self.intermediate_currencies:
                if mid_currency == target_currency:
                    continue

                # 路径: base → mid → target → base
                profit, steps = self._calculate_triangular_profit(
                    exchange_prices,
                    self.base_currency,
                    mid_currency,
                    target_currency,
                )

                if profit and profit > self.min_profit_pct:
                    logger.info(
                        "三角套利 %s: %s→%s→%s→%s 利润 %.4f%%",
                        self.exchange, self.base_currency, mid_currency,
                        target_currency, self.base_currency, profit * 100,
                    )
                    # 产生三笔信号
                    for i, step in enumerate(steps):
                        signals.append(StrategySignal(
                            strategy_name=self.name,
                            symbol=step["symbol"],
                            side=step["side"],
                            price=step["price"],
                            amount=step["amount"],
                            exchange=self.exchange,
                            order_type="limit",
                            reason=f"三角套利步骤{i+1} {self.base_currency}→{mid_currency}→{target_currency}→{self.base_currency}",
                        ))
                        self.record_signal(signals[-1])

        return signals

    def _calculate_triangular_profit(
        self,
        exchange_prices: Dict[str, Dict[str, Any]],
        base: str,
        mid: str,
        target: str,
    ) -> tuple:
        """
        计算三角套利利润

        路径: base → mid → target → base
        步骤1: 用 base 买 mid（买 mid/base 的 ask）
        步骤2: 用 mid 买 target（买 target/mid 的 ask）
        步骤3: 卖 target 换 base（卖 target/base 的 bid）

        Args:
            exchange_prices: 该交易所的价格快照
            base: 基础货币
            mid: 中间货币
            target: 目标货币

        Returns:
            (净利润率, 步骤列表) 或 (None, [])
        """
        amount = self.investment_amount
        steps = []

        # 步骤1: base → mid
        # 买 mid/base：用 base 买 mid，价格为 ask
        symbol1 = f"{mid}/{base}"
        ticker1 = exchange_prices.get(symbol1)
        if not ticker1 or ticker1.get("ask", 0) <= 0:
            return None, []
        ask1 = float(ticker1["ask"])
        mid_amount = amount / ask1
        steps.append({
            "symbol": symbol1, "side": "buy",
            "price": ask1, "amount": mid_amount,
        })

        # 步骤2: mid → target
        # 买 target/mid：用 mid 买 target
        symbol2 = f"{target}/{mid}"
        ticker2 = exchange_prices.get(symbol2)
        if not ticker2 or ticker2.get("ask", 0) <= 0:
            return None, []
        ask2 = float(ticker2["ask"])
        target_amount = mid_amount / ask2
        steps.append({
            "symbol": symbol2, "side": "buy",
            "price": ask2, "amount": target_amount,
        })

        # 步骤3: target → base
        # 卖 target/base：用 target 换 base，价格为 bid
        symbol3 = f"{target}/{base}"
        ticker3 = exchange_prices.get(symbol3)
        if not ticker3 or ticker3.get("bid", 0) <= 0:
            return None, []
        bid3 = float(ticker3["bid"])
        final_base = target_amount * bid3
        steps.append({
            "symbol": symbol3, "side": "sell",
            "price": bid3, "amount": target_amount,
        })

        # 计算净利润率（扣除三边手续费，假设 0.1%）
        fee_rate = 0.001
        total_fee = 3 * fee_rate
        profit = (final_base - amount) / amount - total_fee

        return profit, steps

    def get_status(self) -> Dict[str, Any]:
        """获取三角套利策略状态"""
        status = super().get_status()
        status.update({
            "exchange": self.exchange,
            "base_currency": self.base_currency,
            "intermediate_currencies": self.intermediate_currencies,
            "min_profit_pct": self.min_profit_pct,
            "investment_amount": self.investment_amount,
        })
        return status
