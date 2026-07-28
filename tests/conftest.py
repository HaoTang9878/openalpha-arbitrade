"""
pytest 公共 fixtures

提供所有测试文件共享的测试数据构造器，包括：
- 价格快照、L2 订单簿、套利机会、交易结果等数据模型
- 临时目录的 Config / Database 实例
- 环境变量隔离（避免污染真实环境）
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

# 确保能导入 backend 模块（项目根目录加入 sys.path）
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import Config  # noqa: E402
from backend.models import (  # noqa: E402
    ArbitrageOpportunity,
    OrderStatus,
    RiskLevel,
    TradeResult,
)


# ----------------------------------------------------------------------------
# 环境变量隔离：测试期间清空可能影响配置加载的环境变量
# ----------------------------------------------------------------------------
_PROTECTED_ENV_VARS = (
    "MIN_PROFITABILITY",
    "ORDER_AMOUNT",
    "SCAN_INTERVAL",
    "MAX_ORDER_AGE",
    "PAPER_TRADE",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_MIN_PROFIT_ALERT",
    "ARBITRAGE_API_TOKEN",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """自动 fixture：清空可能影响测试的环境变量，保证测试可重复"""
    for var in _PROTECTED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


# ----------------------------------------------------------------------------
# 价格快照数据
# ----------------------------------------------------------------------------
@pytest.fixture
def sample_prices() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """模拟价格快照数据（binance 低价、okx 高价，存在套利空间）"""
    return {
        "binance": {
            "BTC/USDT": {
                "bid": 95000.0, "ask": 95001.0,
                "last": 95000.5, "volume": 1000000.0,
                "timestamp": 1700000000000,
            },
            "ETH/USDT": {
                "bid": 3200.0, "ask": 3200.5,
                "last": 3200.2, "volume": 500000.0,
                "timestamp": 1700000000000,
            },
        },
        "okx": {
            "BTC/USDT": {
                "bid": 95500.0, "ask": 95501.0,
                "last": 95500.5, "volume": 800000.0,
                "timestamp": 1700000000000,
            },
            "ETH/USDT": {
                "bid": 3210.0, "ask": 3210.5,
                "last": 3210.2, "volume": 400000.0,
                "timestamp": 1700000000000,
            },
        },
    }


@pytest.fixture
def low_volume_prices() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """低交易量价格快照（用于测试流动性风险评级）"""
    return {
        "binance": {
            "BTC/USDT": {
                "bid": 95000.0, "ask": 95001.0,
                "last": 95000.5, "volume": 50000.0,
                "timestamp": 1700000000000,
            },
        },
        "okx": {
            "BTC/USDT": {
                "bid": 95500.0, "ask": 95501.0,
                "last": 95500.5, "volume": 30000.0,
                "timestamp": 1700000000000,
            },
        },
    }


@pytest.fixture
def high_spread_prices() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """高价差价格快照（价差 > 2%，用于测试高风险评级）"""
    return {
        "binance": {
            "BTC/USDT": {
                "bid": 95000.0, "ask": 95001.0,
                "last": 95000.5, "volume": 1000000.0,
                "timestamp": 1700000000000,
            },
        },
        "okx": {
            "BTC/USDT": {
                "bid": 98000.0, "ask": 98001.0,
                "last": 98000.5, "volume": 800000.0,
                "timestamp": 1700000000000,
            },
        },
    }


# ----------------------------------------------------------------------------
# L2 订单簿数据
# ----------------------------------------------------------------------------
@pytest.fixture
def sample_orderbook() -> Dict[str, List[List[float]]]:
    """模拟 L2 订单簿数据（深度充足）"""
    return {
        "bids": [[95000.0, 0.5], [94999.0, 0.3], [94998.0, 0.2]],
        "asks": [[95001.0, 0.3], [95002.0, 0.4], [95003.0, 0.3]],
    }


@pytest.fixture
def shallow_orderbook() -> Dict[str, List[List[float]]]:
    """模拟深度不足的 L2 订单簿（无法满足下单量）"""
    return {
        "bids": [[95000.0, 0.001]],
        "asks": [[95001.0, 0.001]],
    }


@pytest.fixture
def sample_orderbooks() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """模拟多交易所 L2 订单簿缓存（供 detect() 使用）"""
    return {
        "binance": {
            "BTC/USDT": {
                "bids": [[95000.0, 0.5], [94999.0, 0.3]],
                "asks": [[95001.0, 0.3], [95002.0, 0.4]],
            },
        },
        "okx": {
            "BTC/USDT": {
                "bids": [[95500.0, 0.5], [95499.0, 0.3]],
                "asks": [[95101.0, 0.3], [95102.0, 0.4]],
            },
        },
    }


# ----------------------------------------------------------------------------
# 数据模型 fixtures
# ----------------------------------------------------------------------------
@pytest.fixture
def sample_opportunity() -> ArbitrageOpportunity:
    """模拟套利机会"""
    return ArbitrageOpportunity(
        symbol="BTC/USDT",
        buy_exchange="binance",
        sell_exchange="okx",
        buy_price=95001.0,
        sell_price=95100.0,
        spread_percent=0.00104,
        net_profit_rate=0.00084,
        estimated_profit=0.798,
        risk_level=RiskLevel.LOW,
        timestamp=1700000000000,
    )


@pytest.fixture
def high_profit_opportunity() -> ArbitrageOpportunity:
    """高净利润率套利机会（超过 Telegram 告警阈值 0.5%）"""
    return ArbitrageOpportunity(
        symbol="BTC/USDT",
        buy_exchange="binance",
        sell_exchange="okx",
        buy_price=95000.0,
        sell_price=96000.0,
        spread_percent=0.01052,
        net_profit_rate=0.00932,
        estimated_profit=8.85,
        risk_level=RiskLevel.MEDIUM,
        timestamp=1700000000000,
    )


@pytest.fixture
def sample_trade_result() -> TradeResult:
    """模拟交易结果"""
    return TradeResult(
        id="test123",
        symbol="BTC/USDT",
        buy_exchange="binance",
        sell_exchange="okx",
        buy_price=95001.0,
        sell_price=95100.0,
        amount=0.01,
        buy_order_id="PAPER-BUY-test123",
        sell_order_id="PAPER-SELL-test123",
        status=OrderStatus.FILLED,
        profit=0.798,
        paper_trade=True,
        timestamp="2026-07-28 01:00:00",
    )


# ----------------------------------------------------------------------------
# 配置与持久化 fixtures
# ----------------------------------------------------------------------------
@pytest.fixture
def test_config() -> Config:
    """使用最小交易所/交易对集合的配置实例（不读 YAML）"""
    config = Config()
    config.model.exchanges = ["binance", "okx"]
    config.model.symbols = ["BTC/USDT", "ETH/USDT"]
    config.model.min_profitability = 0.001
    config.model.order_amount = 0.01
    config.model.paper_trade = True
    return config


@pytest.fixture
def tmp_db(tmp_path):
    """临时 SQLite 数据库实例（测试后自动清理）"""
    from backend.database import Database

    db_path = str(tmp_path / "test_arbitrage.db")
    db = Database(db_path)
    yield db
    db.close()


@pytest.fixture
def tmp_yaml_config(tmp_path):
    """临时 YAML 配置文件路径"""
    return str(tmp_path / "test_config.yaml")
