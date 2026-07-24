"""
风控管理模块

管理套利交易的风险控制规则，包括：
- 最大同时持仓数限制
- 每日最大亏损限制（超过则停止交易）
- 每日最大交易次数限制
- 单交易所最大敞口限制

风控规则在每次执行交易前检查，不通过则拒绝执行。

使用方法：
    risk_manager = RiskManager(config)
    if risk_manager.check(opportunity, current_prices):
        await executor.execute(opportunity)
        risk_manager.record_trade(result)
"""

import logging
from collections import defaultdict
from datetime import date
from typing import Dict, Optional

from .models import ArbitrageOpportunity, TradeResult

logger = logging.getLogger(__name__)

# 默认风控参数
DEFAULT_MAX_OPEN_POSITIONS = 3       # 最大同时持仓数
DEFAULT_MAX_DAILY_LOSS = 50.0        # 每日最大亏损（USDT）
DEFAULT_MAX_DAILY_TRADES = 100       # 每日最大交易次数
DEFAULT_MAX_EXPOSURE_PER_EX = 500.0  # 单交易所最大敞口（USDT）


class RiskManager:
    """
    风控管理器

    在交易执行前检查风控规则，记录交易结果用于实时风控计算。
    """

    def __init__(self, config=None) -> None:
        """
        初始化风控管理器

        Args:
            config: 系统配置管理器（可选，用于读取风控参数）
        """
        self.config = config

        # 运行时状态
        self._open_positions: int = 0
        self._daily_pnl: float = 0.0
        self._daily_trade_count: int = 0
        self._daily_date: Optional[date] = None
        self._exchange_exposure: Dict[str, float] = defaultdict(float)

        # 风控暂停标记（触发后需手动恢复）
        self._halted: bool = False
        self._halt_reason: str = ""

        self._reset_daily_if_needed()
        logger.info("风控管理器初始化完成")

    def _reset_daily_if_needed(self) -> None:
        """如果日期变更，重置每日统计"""
        today = date.today()
        if self._daily_date != today:
            if self._daily_date is not None:
                logger.info(
                    "每日风控重置：前日交易 %d 笔，盈亏 %.2f USDT",
                    self._daily_trade_count, self._daily_pnl,
                )
            self._daily_date = today
            self._daily_pnl = 0.0
            self._daily_trade_count = 0

    def check(
        self,
        opportunity: ArbitrageOpportunity,
        prices: Optional[Dict] = None,
    ) -> bool:
        """
        检查套利机会是否通过风控规则

        Args:
            opportunity: 套利机会
            prices: 当前价格快照（可选，用于计算敞口）

        Returns:
            是否通过风控检查
        """
        self._reset_daily_if_needed()

        # 检查是否已被暂停
        if self._halted:
            logger.warning("风控拒绝：系统已暂停（%s）", self._halt_reason)
            return False

        # 规则 1：最大同时持仓数
        if self._open_positions >= DEFAULT_MAX_OPEN_POSITIONS:
            logger.warning(
                "风控拒绝：当前持仓 %d 达到上限 %d",
                self._open_positions, DEFAULT_MAX_OPEN_POSITIONS,
            )
            return False

        # 规则 2：每日最大交易次数
        if self._daily_trade_count >= DEFAULT_MAX_DAILY_TRADES:
            self._halt("每日交易次数达到上限 %d" % DEFAULT_MAX_DAILY_TRADES)
            return False

        # 规则 3：每日最大亏损
        if self._daily_pnl <= -DEFAULT_MAX_DAILY_LOSS:
            self._halt(
                "每日亏损 %.2f USDT 超过上限 %.2f"
                % (abs(self._daily_pnl), DEFAULT_MAX_DAILY_LOSS)
            )
            return False

        # 规则 4：单交易所敞口检查
        buy_exposure = self._exchange_exposure[opportunity.buy_exchange]
        sell_exposure = self._exchange_exposure[opportunity.sell_exchange]
        trade_value = opportunity.buy_price * self._get_order_amount()

        if buy_exposure + trade_value > DEFAULT_MAX_EXPOSURE_PER_EX:
            logger.warning(
                "风控拒绝：%s 敞口 %.2f + %.2f 超过上限 %.2f",
                opportunity.buy_exchange, buy_exposure, trade_value,
                DEFAULT_MAX_EXPOSURE_PER_EX,
            )
            return False

        if sell_exposure + trade_value > DEFAULT_MAX_EXPOSURE_PER_EX:
            logger.warning(
                "风控拒绝：%s 敞口 %.2f + %.2f 超过上限 %.2f",
                opportunity.sell_exchange, sell_exposure, trade_value,
                DEFAULT_MAX_EXPOSURE_PER_EX,
            )
            return False

        return True

    def record_trade_start(self, opportunity: ArbitrageOpportunity) -> None:
        """记录交易开始（增加持仓数和敞口）"""
        self._open_positions += 1
        trade_value = opportunity.buy_price * self._get_order_amount()
        self._exchange_exposure[opportunity.buy_exchange] += trade_value
        self._exchange_exposure[opportunity.sell_exchange] += trade_value
        logger.debug(
            "交易开始：%s，持仓数=%d，%s 敞口=%.2f，%s 敞口=%.2f",
            opportunity.symbol, self._open_positions,
            opportunity.buy_exchange,
            self._exchange_exposure[opportunity.buy_exchange],
            opportunity.sell_exchange,
            self._exchange_exposure[opportunity.sell_exchange],
        )

    def record_trade_end(self, result: TradeResult) -> None:
        """记录交易结束（减少持仓数，更新盈亏和敞口）"""
        self._open_positions = max(0, self._open_positions - 1)
        self._daily_pnl += result.profit
        self._daily_trade_count += 1

        # 减少敞口
        trade_value = result.buy_price * result.amount
        self._exchange_exposure[result.buy_exchange] -= trade_value
        self._exchange_exposure[result.sell_exchange] -= trade_value

        # 确保敞口不为负
        if self._exchange_exposure[result.buy_exchange] < 0:
            self._exchange_exposure[result.buy_exchange] = 0
        if self._exchange_exposure[result.sell_exchange] < 0:
            self._exchange_exposure[result.sell_exchange] = 0

        logger.info(
            "交易结束：%s 利润=%.4f，持仓数=%d，日盈亏=%.2f，日交易=%d",
            result.symbol, result.profit, self._open_positions,
            self._daily_pnl, self._daily_trade_count,
        )

    def _halt(self, reason: str) -> None:
        """暂停交易"""
        self._halted = True
        self._halt_reason = reason
        logger.error("风控暂停：%s", reason)

    def resume(self) -> None:
        """恢复交易（手动调用）"""
        self._halted = False
        self._halt_reason = ""
        logger.info("风控已恢复，交易可继续")

    def _get_order_amount(self) -> float:
        """获取当前配置的下单量"""
        if self.config:
            return self.config.model.order_amount
        return 0.01

    def get_status(self) -> Dict:
        """
        获取风控状态

        Returns:
            包含所有风控指标的状态字典
        """
        self._reset_daily_if_needed()
        return {
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "open_positions": self._open_positions,
            "max_open_positions": DEFAULT_MAX_OPEN_POSITIONS,
            "daily_pnl": round(self._daily_pnl, 2),
            "max_daily_loss": DEFAULT_MAX_DAILY_LOSS,
            "daily_trade_count": self._daily_trade_count,
            "max_daily_trades": DEFAULT_MAX_DAILY_TRADES,
            "exchange_exposure": dict(self._exchange_exposure),
            "max_exposure_per_exchange": DEFAULT_MAX_EXPOSURE_PER_EX,
        }
