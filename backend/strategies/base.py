"""
策略基类模块

定义所有交易策略的抽象基类 BaseStrategy，规范策略的生命周期管理接口：
- 启动/停止
- 状态查询
- 配置管理
- 信号生成（由子类实现）

所有具体策略（网格、DCA、三角套利等）继承此类并实现 generate_signals() 方法。
策略由 StrategyOrchestrator 统一调度，支持并发运行多个策略实例。

使用方法：
    class GridStrategy(BaseStrategy):
        async def generate_signals(self, prices):
            ...
"""

import logging
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class StrategyStatus(str, Enum):
    """策略运行状态枚举"""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


class StrategySignal:
    """
    策略信号

    表示策略产生的一个交易信号，包含交易方向、交易对、
    建议价格和数量等信息，由执行器消费。
    """

    def __init__(
        self,
        strategy_name: str,
        symbol: str,
        side: str,
        price: float,
        amount: float,
        exchange: str = "",
        order_type: str = "limit",
        reason: str = "",
    ) -> None:
        """
        初始化策略信号

        Args:
            strategy_name: 产生信号的策略名称
            symbol: 交易对
            side: 买卖方向（buy/sell）
            price: 建议价格
            amount: 建议数量
            exchange: 交易所名称（空表示由执行器选择）
            order_type: 订单类型（limit/market）
            reason: 信号产生原因（用于日志和审计）
        """
        self.strategy_name = strategy_name
        self.symbol = symbol
        self.side = side
        self.price = price
        self.amount = amount
        self.exchange = exchange
        self.order_type = order_type
        self.reason = reason
        self.timestamp = int(time.time() * 1000)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "side": self.side,
            "price": self.price,
            "amount": self.amount,
            "exchange": self.exchange,
            "order_type": self.order_type,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class BaseStrategy(ABC):
    """
    策略抽象基类

    所有交易策略继承此类，实现 generate_signals() 方法。
    基类提供状态管理、配置管理和生命周期控制。
    """

    def __init__(
        self,
        name: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        初始化策略

        Args:
            name: 策略名称（唯一标识）
            config: 策略配置字典
        """
        self.name = name
        self.config = config or {}
        self.status = StrategyStatus.STOPPED
        self._start_time: Optional[float] = None
        self._signal_count = 0
        self._error_count = 0
        self._last_signal_time: Optional[float] = None

        logger.info("策略 %s 已初始化", self.name)

    @abstractmethod
    async def generate_signals(
        self,
        prices: Dict[str, Dict[str, Dict[str, Any]]],
    ) -> List[StrategySignal]:
        """
        生成交易信号（由子类实现）

        根据当前价格快照分析市场状况，产生交易信号。
        由 StrategyOrchestrator 定期调用。

        Args:
            prices: 价格快照 {exchange: {symbol: {bid, ask, last, volume, timestamp}}}

        Returns:
            策略信号列表
        """
        ...

    async def start(self) -> None:
        """启动策略"""
        if self.status == StrategyStatus.RUNNING:
            logger.warning("策略 %s 已在运行", self.name)
            return
        self.status = StrategyStatus.RUNNING
        self._start_time = time.time()
        logger.info("策略 %s 已启动", self.name)

    async def stop(self) -> None:
        """停止策略"""
        self.status = StrategyStatus.STOPPED
        logger.info("策略 %s 已停止", self.name)

    async def pause(self) -> None:
        """暂停策略"""
        if self.status == StrategyStatus.RUNNING:
            self.status = StrategyStatus.PAUSED
            logger.info("策略 %s 已暂停", self.name)

    async def resume(self) -> None:
        """恢复策略"""
        if self.status == StrategyStatus.PAUSED:
            self.status = StrategyStatus.RUNNING
            logger.info("策略 %s 已恢复", self.name)

    def update_config(self, config: Dict[str, Any]) -> None:
        """
        更新策略配置

        Args:
            config: 新的配置字典（部分更新）
        """
        self.config.update(config)
        logger.info("策略 %s 配置已更新: %s", self.name, list(config.keys()))

    def record_signal(self, signal: StrategySignal) -> None:
        """记录信号统计"""
        self._signal_count += 1
        self._last_signal_time = time.time()

    def record_error(self) -> None:
        """记录错误"""
        self._error_count += 1
        if self._error_count > 10:
            self.status = StrategyStatus.ERROR
            logger.error(
                "策略 %s 错误次数过多（%d），已标记为 ERROR 状态",
                self.name, self._error_count,
            )

    def get_status(self) -> Dict[str, Any]:
        """
        获取策略状态

        Returns:
            策略状态字典，包含运行状态、信号数、错误数、运行时长等
        """
        uptime = time.time() - self._start_time if self._start_time else 0
        return {
            "name": self.name,
            "status": self.status.value,
            "signal_count": self._signal_count,
            "error_count": self._error_count,
            "uptime_seconds": int(uptime),
            "last_signal_time": self._last_signal_time,
            "config": self.config,
        }
