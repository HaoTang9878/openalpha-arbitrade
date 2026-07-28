"""
网格交易机器人策略模块

在设定的价格区间内自动低买高卖，适合震荡行情。
核心逻辑：
1. 设定价格上下限和网格数量，将区间均分为多个网格档位
2. 每个网格档位挂一个买单（低于当前价）和一个卖单（高于当前价）
3. 价格下跌触发买单成交，价格上涨触发卖单成交
4. 每完成一轮买卖赚取网格利润

配置参数：
    symbol: 交易对（如 BTC/USDT）
    exchange: 交易所名称
    lower_price: 价格区间下限
    upper_price: 价格区间上限
    grid_count: 网格数量
    total_investment: 总投资额（USDT）
    stop_loss_pct: 止损百分比（跌破下限后再跌此比例止损）
"""

import logging
import time
from typing import Any, Dict, List

from .base import BaseStrategy, StrategySignal

logger = logging.getLogger(__name__)


class GridStrategy(BaseStrategy):
    """
    网格交易机器人

    在价格区间内自动挂网格买卖单，赚取震荡价差。
    """

    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        """
        初始化网格策略

        Args:
            name: 策略实例名称
            config: 配置字典，必须包含 symbol/exchange/lower_price/
                    upper_price/grid_count/total_investment
        """
        super().__init__(name, config)

        # 必需配置
        self.symbol = config.get("symbol", "BTC/USDT")
        self.exchange = config.get("exchange", "binance")
        self.lower_price = float(config.get("lower_price", 0))
        self.upper_price = float(config.get("upper_price", 0))
        self.grid_count = int(config.get("grid_count", 10))
        self.total_investment = float(config.get("total_investment", 1000))

        # 可选配置
        self.stop_loss_pct = float(config.get("stop_loss_pct", 0.05))

        # 计算网格参数
        self._grid_prices: List[float] = []
        self._grid_amount: float = 0.0
        self._last_price: float = 0.0
        self._filled_grids: set = set()

        self._calculate_grid()

    def _calculate_grid(self) -> None:
        """计算网格价格档位和每格下单量"""
        if self.lower_price <= 0 or self.upper_price <= 0 or self.grid_count <= 0:
            logger.warning("网格参数无效，跳过计算: %s", self.name)
            return

        # 均分网格价格
        step = (self.upper_price - self.lower_price) / self.grid_count
        self._grid_prices = [
            self.lower_price + i * step for i in range(self.grid_count + 1)
        ]

        # 每格下单量（USDT 均分到每个网格）
        self._grid_amount = self.total_investment / self.grid_count

        logger.info(
            "网格 %s 计算完成: %s %s 区间[%.2f-%.2f] %d 格 每格 %.2f USDT",
            self.name, self.exchange, self.symbol,
            self.lower_price, self.upper_price,
            self.grid_count, self._grid_amount,
        )

    async def generate_signals(
        self,
        prices: Dict[str, Dict[str, Dict[str, Any]]],
    ) -> List[StrategySignal]:
        """
        生成网格交易信号

        根据当前价格与网格档位的关系，产生买入或卖出信号：
        - 价格跌破某个网格档位 → 买入信号
        - 价格涨破某个网格档位 → 卖出信号
        - 价格跌破止损线 → 全部卖出止损

        Args:
            prices: 价格快照

        Returns:
            交易信号列表
        """
        if self.status.value != "running":
            return []

        if not self._grid_prices:
            return []

        # 获取当前价格
        ticker = prices.get(self.exchange, {}).get(self.symbol)
        if not ticker or ticker.get("last", 0) <= 0:
            return []

        current_price = float(ticker["last"])
        signals: List[StrategySignal] = []

        # 止损检查
        stop_loss_price = self.lower_price * (1 - self.stop_loss_pct)
        if current_price <= stop_loss_price:
            logger.warning(
                "网格 %s 触发止损: 当前价 %.2f <= 止损价 %.2f",
                self.name, current_price, stop_loss_price,
            )
            signals.append(StrategySignal(
                strategy_name=self.name,
                symbol=self.symbol,
                side="sell",
                price=current_price,
                amount=self._grid_amount / current_price,
                exchange=self.exchange,
                order_type="market",
                reason="止损卖出",
            ))
            self.record_signal(signals[-1])
            return signals

        # 价格下跌：检查是否跌破新的网格档位 → 买入
        if self._last_price > 0 and current_price < self._last_price:
            for i, grid_price in enumerate(self._grid_prices):
                if (
                    self._last_price > grid_price >= current_price
                    and i not in self._filled_grids
                ):
                    buy_amount = self._grid_amount / grid_price
                    signals.append(StrategySignal(
                        strategy_name=self.name,
                        symbol=self.symbol,
                        side="buy",
                        price=grid_price,
                        amount=buy_amount,
                        exchange=self.exchange,
                        order_type="limit",
                        reason=f"网格买入 档位{i} @{grid_price:.2f}",
                    ))
                    self._filled_grids.add(i)
                    self.record_signal(signals[-1])
                    logger.debug(
                        "网格 %s 买入信号: 档位%d @%.2f 数量%.6f",
                        self.name, i, grid_price, buy_amount,
                    )

        # 价格上涨：检查是否涨破已买入的网格档位 → 卖出
        if self._last_price > 0 and current_price > self._last_price:
            for i in list(self._filled_grids):
                grid_price = self._grid_prices[i]
                if current_price >= grid_price:
                    sell_amount = self._grid_amount / grid_price
                    signals.append(StrategySignal(
                        strategy_name=self.name,
                        symbol=self.symbol,
                        side="sell",
                        price=grid_price,
                        amount=sell_amount,
                        exchange=self.exchange,
                        order_type="limit",
                        reason=f"网格卖出 档位{i} @{grid_price:.2f}",
                    ))
                    self._filled_grids.discard(i)
                    self.record_signal(signals[-1])
                    logger.debug(
                        "网格 %s 卖出信号: 档位%d @%.2f 数量%.6f",
                        self.name, i, grid_price, sell_amount,
                    )

        # 更新上次价格
        self._last_price = current_price
        return signals

    def get_status(self) -> Dict[str, Any]:
        """获取网格策略状态（含网格详情）"""
        status = super().get_status()
        status.update({
            "symbol": self.symbol,
            "exchange": self.exchange,
            "lower_price": self.lower_price,
            "upper_price": self.upper_price,
            "grid_count": self.grid_count,
            "filled_grids": len(self._filled_grids),
            "last_price": self._last_price,
            "grid_amount_usdt": round(self._grid_amount, 2),
        })
        return status
