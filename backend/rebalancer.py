"""
库存再平衡模块

跨交易所资金自动调拨，确保各所余额比例均衡。
核心逻辑：
1. 定期检查各交易所余额分布
2. 当某所余额偏离目标比例超过阈值时，触发再平衡
3. 通过内部转账（同一交易所子账户）或链上转账调拨资金
4. 避免因余额不均导致套利机会无法执行

配置参数：
    exchanges: 交易所列表
    target_ratios: 各所目标资金比例
    rebalance_threshold: 触发再平衡的偏离阈值（默认 0.2 = 20%）
    min_transfer_amount: 最小转账金额（USDT）
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class InventoryRebalancer:
    """库存再平衡器"""

    def __init__(
        self,
        exchanges: List[str],
        target_ratios: Optional[Dict[str, float]] = None,
        rebalance_threshold: float = 0.2,
        min_transfer_amount: float = 50.0,
    ) -> None:
        self.exchanges = exchanges
        self.rebalance_threshold = rebalance_threshold
        self.min_transfer_amount = min_transfer_amount

        # 默认均分
        if target_ratios is None:
            equal = 1.0 / len(exchanges)
            self.target_ratios = {ex: equal for ex in exchanges}
        else:
            self.target_ratios = target_ratios

        self._last_rebalance: float = 0
        self._rebalance_cooldown = 3600  # 1小时冷却

    def check_imbalance(
        self, balances: Dict[str, Dict[str, float]]
    ) -> List[Dict[str, Any]]:
        """
        检查余额不均衡情况，返回需要调拨的指令列表

        Args:
            balances: {exchange: {"USDT": 1000, "BTC": 0.5, ...}}

        Returns:
            转账指令列表 [{from, to, asset, amount}]
        """
        # 计算 USDT 总额
        total_usdt = sum(
            b.get("USDT", 0) for b in balances.values()
        )
        if total_usdt <= 0:
            return []

        transfers: List[Dict[str, Any]] = []
        now = time.time()

        # 冷却期检查
        if now - self._last_rebalance < self._rebalance_cooldown:
            return []

        for ex in self.exchanges:
            current = balances.get(ex, {}).get("USDT", 0)
            current_ratio = current / total_usdt if total_usdt > 0 else 0
            target_ratio = self.target_ratios.get(ex, 0)
            deviation = abs(current_ratio - target_ratio)

            if deviation > self.rebalance_threshold:
                target_amount = total_usdt * target_ratio
                diff = target_amount - current

                if abs(diff) < self.min_transfer_amount:
                    continue

                if diff < 0:
                    # 该所余额过多，需要转出
                    surplus_exchanges = [
                        e for e in self.exchanges
                        if balances.get(e, {}).get("USDT", 0)
                        > total_usdt * self.target_ratios.get(e, 0)
                    ]
                    for target_ex in surplus_exchanges:
                        target_diff = (
                            total_usdt * self.target_ratios.get(target_ex, 0)
                            - balances.get(target_ex, {}).get("USDT", 0)
                        )
                        if target_diff > self.min_transfer_amount:
                            transfer_amount = min(abs(diff), target_diff)
                            transfers.append({
                                "from": ex,
                                "to": target_ex,
                                "asset": "USDT",
                                "amount": round(transfer_amount, 2),
                                "reason": f"{ex} 偏离目标 {deviation:.1%}",
                            })
                            break

        if transfers:
            self._last_rebalance = now
            logger.info(
                "库存再平衡: 检测到 %d 笔调拨需求 (总资金 %.0f USDT)",
                len(transfers), total_usdt,
            )

        return transfers

    def get_status(self) -> Dict[str, Any]:
        return {
            "exchanges": self.exchanges,
            "target_ratios": self.target_ratios,
            "rebalance_threshold": self.rebalance_threshold,
            "last_rebalance": self._last_rebalance,
        }
