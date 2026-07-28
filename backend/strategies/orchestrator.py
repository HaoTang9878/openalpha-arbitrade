"""
策略调度器模块

统一调度多个策略实例，定期调用各策略的 generate_signals() 方法，
收集信号并合并去重，交给执行器处理。

核心功能：
- 并发运行多个策略实例
- 定期调用策略生成信号
- 信号合并与去重
- 策略状态监控

使用方法：
    orchestrator = StrategyOrchestrator(registry, executor)
    await orchestrator.start()
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from .base import BaseStrategy, StrategySignal
from .registry import StrategyRegistry

logger = logging.getLogger(__name__)

# 策略调度间隔（秒）
ORCHESTRATOR_INTERVAL = 5


class StrategyOrchestrator:
    """
    策略调度器

    定期调用所有运行中策略的 generate_signals()，
    收集信号并广播。
    """

    def __init__(
        self,
        registry: StrategyRegistry,
        signal_callback: Optional[Any] = None,
    ) -> None:
        """
        初始化调度器

        Args:
            registry: 策略注册中心
            signal_callback: 信号回调函数（async），收到信号时调用
        """
        self.registry = registry
        self.signal_callback = signal_callback
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_signals: List[Dict[str, Any]] = []

    async def start(self) -> None:
        """启动调度器"""
        if self._running:
            logger.warning("策略调度器已在运行")
            return
        self._running = True
        await self.registry.start_all()
        self._task = asyncio.create_task(self._orchestrate_loop())
        logger.info("策略调度器已启动")

    async def stop(self) -> None:
        """停止调度器"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.registry.stop_all()
        logger.info("策略调度器已停止")

    async def _orchestrate_loop(self) -> None:
        """策略调度主循环"""
        while self._running:
            try:
                # 获取最新价格（由外部注入）
                prices = await self._get_prices()
                if not prices:
                    await asyncio.sleep(ORCHESTRATOR_INTERVAL)
                    continue

                # 并发调用所有运行中策略
                all_signals: List[StrategySignal] = []
                for strategy in self.registry.list_all():
                    if strategy.status.value != "running":
                        continue
                    try:
                        signals = await strategy.generate_signals(prices)
                        all_signals.extend(signals)
                    except Exception as e:
                        logger.error(
                            "策略 %s 生成信号失败: %s",
                            strategy.name, e, exc_info=True,
                        )
                        strategy.record_error()

                # 处理信号
                if all_signals:
                    self._last_signals = [s.to_dict() for s in all_signals]
                    logger.info(
                        "策略调度器收集到 %d 个信号（来自 %d 个策略）",
                        len(all_signals), len(self.registry.list_all()),
                    )
                    if self.signal_callback:
                        await self.signal_callback(all_signals)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("策略调度循环异常: %s", e, exc_info=True)

            await asyncio.sleep(ORCHESTRATOR_INTERVAL)

    async def _get_prices(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        获取最新价格快照

        由外部设置 prices_provider 属性，调用其返回价格数据。
        """
        provider = getattr(self, "prices_provider", None)
        if provider:
            if asyncio.iscoroutine(provider):
                return await provider
            return provider
        return {}

    def set_prices_provider(self, provider: Any) -> None:
        """
        设置价格数据提供者

        Args:
            provider: 可以是字典、同步函数或异步函数，返回价格快照
        """
        self.prices_provider = provider

    def get_status(self) -> Dict[str, Any]:
        """获取调度器状态"""
        return {
            "running": self._running,
            "strategy_count": len(self.registry.list_all()),
            "strategies": self.registry.get_all_status(),
            "last_signal_count": len(self._last_signals),
            "last_signals": self._last_signals[:10],
        }
