"""
策略注册中心模块

管理所有策略实例的注册、查找和生命周期控制。
支持动态注册/注销策略，按名称查找策略实例。

使用方法：
    registry = StrategyRegistry()
    registry.register("grid_btc", GridStrategy(...))
    strategy = registry.get("grid_btc")
    all_strategies = registry.list_all()
"""

import logging
from typing import Dict, List, Optional

from .base import BaseStrategy

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """
    策略注册中心

    集中管理所有策略实例，提供注册、查找、列表和批量控制接口。
    每个策略实例有唯一的名称作为 key。
    """

    def __init__(self) -> None:
        """初始化空的策略注册表"""
        self._strategies: Dict[str, BaseStrategy] = {}

    def register(self, name: str, strategy: BaseStrategy) -> None:
        """
        注册策略实例

        Args:
            name: 策略名称（唯一标识）
            strategy: 策略实例
        """
        if name in self._strategies:
            logger.warning("策略 %s 已存在，将被覆盖", name)
        self._strategies[name] = strategy
        logger.info("已注册策略: %s", name)

    def unregister(self, name: str) -> Optional[BaseStrategy]:
        """
        注销策略实例

        Args:
            name: 策略名称

        Returns:
            被移除的策略实例，不存在返回 None
        """
        strategy = self._strategies.pop(name, None)
        if strategy:
            logger.info("已注销策略: %s", name)
        return strategy

    def get(self, name: str) -> Optional[BaseStrategy]:
        """
        按名称获取策略实例

        Args:
            name: 策略名称

        Returns:
            策略实例，不存在返回 None
        """
        return self._strategies.get(name)

    def list_all(self) -> List[BaseStrategy]:
        """获取所有已注册的策略实例"""
        return list(self._strategies.values())

    def list_names(self) -> List[str]:
        """获取所有已注册的策略名称"""
        return list(self._strategies.keys())

    async def start_all(self) -> None:
        """启动所有已注册的策略"""
        for strategy in self._strategies.values():
            try:
                await strategy.start()
            except Exception as e:
                logger.error("启动策略 %s 失败: %s", strategy.name, e)

    async def stop_all(self) -> None:
        """停止所有已注册的策略"""
        for strategy in self._strategies.values():
            try:
                await strategy.stop()
            except Exception as e:
                logger.error("停止策略 %s 失败: %s", strategy.name, e)

    def get_all_status(self) -> List[Dict]:
        """获取所有策略的状态"""
        return [s.get_status() for s in self._strategies.values()]
