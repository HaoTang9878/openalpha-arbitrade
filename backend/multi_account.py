"""
多账户 API Key 轮换模块

支持同一交易所配置多套 API Key，自动轮换使用，避免单 Key 限频。
核心功能：
- 按交易所分组管理多套 API Key
- 请求时自动选择使用次数最少的 Key
- Key 失效时自动降级到备用 Key
- 统计各 Key 使用次数和错误率

配置格式（config.yaml 或环境变量）：
    exchange_api_keys:
      binance:
        - {apiKey: "xxx", secret: "yyy"}
        - {apiKey: "aaa", secret: "bbb"}
      okx:
        - {apiKey: "xxx", secret: "yyy", password: "zzz"}
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class MultiAccountManager:
    """多账户 API Key 轮换管理器"""

    def __init__(self) -> None:
        # {exchange: [{apiKey, secret, password?, usage_count, error_count, disabled}]}
        self._keys: Dict[str, List[Dict[str, Any]]] = {}
        self._lock_count = 0

    def add_keys(
        self,
        exchange: str,
        keys: List[Dict[str, str]],
    ) -> None:
        """为交易所添加多套 API Key"""
        if exchange not in self._keys:
            self._keys[exchange] = []
        for k in keys:
            self._keys[exchange].append({
                "apiKey": k.get("apiKey", ""),
                "secret": k.get("secret", ""),
                "password": k.get("password", ""),
                "usage_count": 0,
                "error_count": 0,
                "disabled": False,
            })
        logger.info(
            "交易所 %s 已加载 %d 套 API Key",
            exchange, len(self._keys[exchange]),
        )

    def get_keys(self, exchange: str) -> Optional[Dict[str, str]]:
        """
        获取使用次数最少的可用 API Key

        Returns:
            {apiKey, secret, password} 或 None
        """
        keys = self._keys.get(exchange, [])
        available = [k for k in keys if not k["disabled"]]
        if not available:
            return None

        # 选择使用次数最少的
        selected = min(available, key=lambda x: x["usage_count"])
        selected["usage_count"] += 1
        return {
            "apiKey": selected["apiKey"],
            "secret": selected["secret"],
            "password": selected.get("password", ""),
        }

    def report_error(self, exchange: str, api_key: str) -> None:
        """报告某个 Key 出错，累计错误达到阈值时禁用"""
        keys = self._keys.get(exchange, [])
        for k in keys:
            if k["apiKey"] == api_key:
                k["error_count"] += 1
                if k["error_count"] >= 10:
                    k["disabled"] = True
                    logger.warning(
                        "交易所 %s 的 API Key %s 已禁用（错误次数过多）",
                        exchange, api_key[:8] + "...",
                    )
                break

    def get_status(self) -> Dict[str, Any]:
        """获取所有 Key 的状态（脱敏）"""
        result = {}
        for ex, keys in self._keys.items():
            result[ex] = [
                {
                    "api_key": k["apiKey"][:8] + "...",
                    "usage_count": k["usage_count"],
                    "error_count": k["error_count"],
                    "disabled": k["disabled"],
                }
                for k in keys
            ]
        return result
