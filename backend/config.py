"""
套利系统配置管理模块

管理系统运行所需的全部配置参数，包括：
- 交易所列表及其 API 密钥
- 套利策略参数（最小利润率、下单量等）
- 监控的交易对列表
- 手续费率配置

配置加载优先级（从高到低）：
1. 通过 API 动态修改的值
2. 环境变量
3. YAML 配置文件（config.yaml）
4. 代码内置默认值

使用方法：
    config = Config()
    config.load_yaml("my_config.yaml")
    config.update({"min_profitability": 0.005})
    print(config.to_dict())
"""

import os
import logging
from typing import Any, Dict, List, Optional

import yaml

from .models import SystemConfig

logger = logging.getLogger(__name__)

# 支持的交易所列表（使用 CCXT 库，前期聚焦 6 个主流所）
SUPPORTED_EXCHANGES: List[str] = [
    "binance", "okx", "bybit", "gate",
    "kucoin", "kraken", "mexc", "htx",
]

# 币种分类映射（用于前端筛选与统计）
SYMBOL_CATEGORIES: Dict[str, List[str]] = {
    "main": ["BTC", "ETH", "SOL", "BNB", "XRP"],
    "defi": ["DOGE", "AVAX", "ARB", "OP", "LINK", "UNI",
             "AAVE", "MKR", "CRV", "SNX"],
    "layer2": ["MATIC", "STRK", "BLUR"],
    "ai": ["FET", "AGIX", "RNDR", "TAO"],
    "rwa": ["ONDO", "PENDLE"],
    "chain": ["SUI", "SEI", "TIA", "INJ", "APT", "NEAR", "ATOM", "DOT"],
    "meme": ["PEPE", "WIF", "BONK", "FLOKI", "SHIB"],
    "ecosystem": ["LDO", "ENA"],
    "platform": ["GT", "CRO"],
}

# 默认监控的交易对列表（40 个，覆盖 9 大赛道）
DEFAULT_SYMBOLS: List[str] = [
    # 主流币（5）
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    # DeFi（10）
    "DOGE/USDT", "AVAX/USDT", "ARB/USDT", "OP/USDT", "LINK/USDT",
    "UNI/USDT", "AAVE/USDT", "MKR/USDT", "CRV/USDT", "SNX/USDT",
    # Layer2（3）
    "MATIC/USDT", "STRK/USDT", "BLUR/USDT",
    # AI（4）
    "FET/USDT", "AGIX/USDT", "RNDR/USDT", "TAO/USDT",
    # RWA（2）
    "ONDO/USDT", "PENDLE/USDT",
    # 新公链（8）
    "SUI/USDT", "SEI/USDT", "TIA/USDT", "INJ/USDT",
    "APT/USDT", "NEAR/USDT", "ATOM/USDT", "DOT/USDT",
    # Meme（5）
    "PEPE/USDT", "WIF/USDT", "BONK/USDT", "FLOKI/USDT", "SHIB/USDT",
    # 稳定币生态（2）
    "LDO/USDT", "ENA/USDT",
    # 交易所平台币（1）
    "CRO/USDT",
]

# 按价格区间自动配置下单量（名义价值约 50-100 USDT）
# 套利检测时根据交易对最优 ask 价格自动选择对应档位的下单量
ORDER_AMOUNT_BY_PRICE: Dict[str, Dict[str, float]] = {
    "high":  {"max_price": 999999, "amount": 0.001},   # BTC/ETH 等高价币
    "mid":   {"max_price": 100,     "amount": 0.1},     # SOL/BNB/LINK 等
    "low":   {"max_price": 10,      "amount": 5},       # DOGE/ARB/OP 等
    "micro": {"max_price": 1,       "amount": 50},      # PEPE/SHIB 等
    "nano":  {"max_price": 0.1,     "amount": 1000},    # BONK/FLOKI 等
}


def get_order_amount_for_price(price: float) -> float:
    """
    根据交易对价格自动选择合适的下单量

    按名义价值约 50-100 USDT 分级，确保不同价格币种的下单量合理，
    避免高价币下单量过大或低价币下单量过小。

    Args:
        price: 交易对的最优 ask 价格

    Returns:
        对应档位的下单量（基础货币数量）
    """
    if price <= 0:
        return ORDER_AMOUNT_BY_PRICE["micro"]["amount"]
    for tier in ("nano", "micro", "low", "mid", "high"):
        if price <= ORDER_AMOUNT_BY_PRICE[tier]["max_price"]:
            return ORDER_AMOUNT_BY_PRICE[tier]["amount"]
    return ORDER_AMOUNT_BY_PRICE["high"]["amount"]


def get_symbol_category(symbol: str) -> str:
    """
    获取交易对所属的分类标签

    Args:
        symbol: 交易对，如 BTC/USDT

    Returns:
        分类名称（main/defi/layer2/ai/rwa/chain/meme/ecosystem/platform），
        未匹配返回 other
    """
    base = symbol.split("/")[0] if "/" in symbol else symbol
    for category, symbols in SYMBOL_CATEGORIES.items():
        if base in symbols:
            return category
    return "other"

# 默认配置参数
DEFAULT_CONFIG: Dict[str, Any] = {
    "min_profitability": 0.001,  # 0.1% — 必须为正，覆盖手续费波动
    "order_amount": 0.01,
    "scan_interval": 3,
    "max_order_age": 60,         # 缩短至 60s，降低敞口时间
    "paper_trade": True,
    "fee_rate": 0.001,
    "top_n_opportunities": 30,   # 扩大返回数量便于统计
}


class Config:
    """
    配置管理类

    负责加载、存储和动态修改系统配置。
    支持从环境变量、YAML 文件加载，以及通过 API 动态修改。
    """

    def __init__(self, config_path: Optional[str] = None) -> None:
        """
        初始化配置管理器

        Args:
            config_path: YAML 配置文件路径，可选
        """
        self.model = SystemConfig(
            exchanges=SUPPORTED_EXCHANGES.copy(),
            symbols=DEFAULT_SYMBOLS.copy(),
            min_profitability=DEFAULT_CONFIG["min_profitability"],
            order_amount=DEFAULT_CONFIG["order_amount"],
            scan_interval=DEFAULT_CONFIG["scan_interval"],
            max_order_age=DEFAULT_CONFIG["max_order_age"],
            paper_trade=DEFAULT_CONFIG["paper_trade"],
            fee_rate=DEFAULT_CONFIG["fee_rate"],
            top_n_opportunities=DEFAULT_CONFIG["top_n_opportunities"],
        )

        # 初始化各交易所手续费率（默认全部为 0.1%）
        self.model.exchange_fees = {
            ex: self.model.fee_rate for ex in SUPPORTED_EXCHANGES
        }

        # 存储 API 密钥（不序列化到配置字典）
        self.api_keys: Dict[str, Dict[str, str]] = {}

        # 从环境变量加载
        self._load_from_env()

        # 从 YAML 文件加载
        if config_path:
            self.load_yaml(config_path)

        logger.info("配置管理器初始化完成，启用交易所 %d 个，监控交易对 %d 个",
                     len(self.model.exchanges), len(self.model.symbols))

    def _load_from_env(self) -> None:
        """从环境变量加载配置，覆盖默认值"""
        try:
            if os.getenv("MIN_PROFITABILITY"):
                self.model.min_profitability = float(
                    os.getenv("MIN_PROFITABILITY")
                )
            if os.getenv("ORDER_AMOUNT"):
                self.model.order_amount = float(os.getenv("ORDER_AMOUNT"))
            if os.getenv("SCAN_INTERVAL"):
                self.model.scan_interval = int(os.getenv("SCAN_INTERVAL"))
            if os.getenv("MAX_ORDER_AGE"):
                self.model.max_order_age = int(os.getenv("MAX_ORDER_AGE"))
            if os.getenv("PAPER_TRADE"):
                self.model.paper_trade = os.getenv(
                    "PAPER_TRADE", "true"
                ).lower() == "true"

            # 从环境变量加载交易所 API 密钥
            # 格式：BINANCE_API_KEY, BINANCE_API_SECRET 等
            for ex in SUPPORTED_EXCHANGES:
                prefix = ex.upper()
                api_key = os.getenv(f"{prefix}_API_KEY", "")
                api_secret = os.getenv(f"{prefix}_API_SECRET", "")
                if api_key and api_secret:
                    self.api_keys[ex] = {
                        "apiKey": api_key,
                        "secret": api_secret,
                    }
                    logger.debug("已加载 %s 交易所的 API 密钥", ex)
        except Exception as e:
            logger.error("从环境变量加载配置失败: %s", e, exc_info=True)

    def load_yaml(self, path: str) -> None:
        """
        从 YAML 文件加载配置

        Args:
            path: YAML 文件路径
        """
        try:
            if not os.path.exists(path):
                logger.warning("配置文件不存在: %s，使用默认配置", path)
                return

            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if data is None:
                logger.warning("配置文件为空: %s", path)
                return

            self.update(data)
            logger.info("已从 %s 加载配置", path)
        except yaml.YAMLError as e:
            logger.error("解析 YAML 配置文件失败: %s", e, exc_info=True)
        except Exception as e:
            logger.error("加载配置文件失败: %s", e, exc_info=True)

    def update(self, data: Dict[str, Any]) -> None:
        """
        动态更新配置

        Args:
            data: 包含配置项的字典，只更新提供的字段
        """
        try:
            if "exchanges" in data and isinstance(data["exchanges"], list):
                # 验证交易所名称是否受支持
                valid = [ex for ex in data["exchanges"] if ex in SUPPORTED_EXCHANGES]
                if valid:
                    self.model.exchanges = valid

            if "symbols" in data and isinstance(data["symbols"], list):
                self.model.symbols = data["symbols"]

            if "min_profitability" in data:
                self.model.min_profitability = float(data["min_profitability"])

            if "order_amount" in data:
                self.model.order_amount = float(data["order_amount"])

            if "scan_interval" in data:
                self.model.scan_interval = int(data["scan_interval"])

            if "max_order_age" in data:
                self.model.max_order_age = int(data["max_order_age"])

            if "paper_trade" in data:
                self.model.paper_trade = bool(data["paper_trade"])

            if "fee_rate" in data:
                self.model.fee_rate = float(data["fee_rate"])

            if "top_n_opportunities" in data:
                self.model.top_n_opportunities = int(data["top_n_opportunities"])

            if "exchange_fees" in data and isinstance(data["exchange_fees"], dict):
                self.model.exchange_fees.update(data["exchange_fees"])

            # 从 YAML 加载 API 密钥（格式：api_keys: {binance: {apiKey: xx, secret: xx}}）
            if "api_keys" in data and isinstance(data["api_keys"], dict):
                for ex_name, keys in data["api_keys"].items():
                    if isinstance(keys, dict) and keys.get("apiKey") and keys.get("secret"):
                        self.api_keys[ex_name] = {
                            "apiKey": keys["apiKey"],
                            "secret": keys["secret"],
                        }
                        logger.debug("已从 YAML 加载 %s 的 API 密钥", ex_name)

            logger.info("配置已更新")
        except (ValueError, TypeError) as e:
            logger.error("更新配置失败: %s", e, exc_info=True)

    def to_dict(self) -> Dict[str, Any]:
        """
        将配置转换为字典

        Returns:
            包含所有配置项的字典（不含 API 密钥明文，仅含配置状态）
        """
        data = self.model.model_dump()
        # 添加 API Key 配置状态（不暴露密钥本身）
        data["api_key_status"] = {
            ex: ex in self.api_keys for ex in self.model.exchanges
        }
        return data

    def get_exchange_fee(self, exchange: str) -> float:
        """
        获取指定交易所的手续费率

        Args:
            exchange: 交易所名称

        Returns:
            手续费率，若未配置则返回默认费率
        """
        return self.model.exchange_fees.get(
            exchange, self.model.fee_rate
        )
