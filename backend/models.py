"""
数据模型模块

使用 Pydantic 定义系统核心数据模型，包括：
- PriceSnapshot: 价格快照，记录单个交易所单个交易对的实时价格
- ArbitrageOpportunity: 套利机会，描述跨交易所价差套利方案
- TradeResult: 交易结果，记录单笔套利交易的执行状态
- ExchangeStatus: 交易所状态，记录交易所连接和运行状态
- SystemConfig: 系统配置，管理套利系统的运行参数

所有模型均使用 Pydantic v2 进行数据验证和序列化。
"""

from enum import Enum
from typing import Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """风险等级枚举，用于标识套利机会的风险程度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OrderStatus(str, Enum):
    """订单状态枚举，用于跟踪订单生命周期"""
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class PriceSnapshot(BaseModel):
    """
    价格快照模型

    记录单个交易所中某个交易对在某一时刻的完整价格信息，
    包括买一价、卖一价、最新成交价和成交量。
    """
    exchange: str = Field(..., description="交易所名称")
    symbol: str = Field(..., description="交易对，如 BTC/USDT")
    bid: float = Field(0.0, description="买一价（最高买价）")
    ask: float = Field(0.0, description="卖一价（最低卖价）")
    last: float = Field(0.0, description="最新成交价")
    volume: float = Field(0.0, description="24小时成交量")
    timestamp: int = Field(0, description="数据时间戳（毫秒）")


class ArbitrageOpportunity(BaseModel):
    """
    套利机会模型

    描述一个跨交易所套利方案：在低价交易所买入，
    同时在高价交易所卖出，赚取价差利润。
    """
    symbol: str = Field(..., description="交易对")
    buy_exchange: str = Field(..., description="买入交易所（ask最低）")
    sell_exchange: str = Field(..., description="卖出交易所（bid最高）")
    buy_price: float = Field(..., description="买入价格（卖一价）")
    sell_price: float = Field(..., description="卖出价格（买一价）")
    spread_percent: float = Field(..., description="原始价差百分比")
    net_profit_rate: float = Field(..., description="扣除手续费后的净利润率")
    estimated_profit: float = Field(..., description="预计净利润（USDT）")
    risk_level: RiskLevel = Field(RiskLevel.MEDIUM, description="风险等级")
    timestamp: int = Field(0, description="检测时间戳（毫秒）")


class TradeResult(BaseModel):
    """
    交易结果模型

    记录单笔套利交易的执行结果，包括买卖双方的订单信息和最终状态。
    """
    id: str = Field("", description="交易记录ID")
    symbol: str = Field(..., description="交易对")
    buy_exchange: str = Field(..., description="买入交易所")
    sell_exchange: str = Field(..., description="卖出交易所")
    buy_price: float = Field(0.0, description="实际买入价格")
    sell_price: float = Field(0.0, description="实际卖出价格")
    amount: float = Field(0.0, description="交易数量（基础货币）")
    buy_order_id: Optional[str] = Field(None, description="买入订单ID")
    sell_order_id: Optional[str] = Field(None, description="卖出订单ID")
    status: OrderStatus = Field(OrderStatus.PENDING, description="交易状态")
    profit: float = Field(0.0, description="实际利润（USDT）")
    error: Optional[str] = Field(None, description="错误信息")
    paper_trade: bool = Field(True, description="是否为模拟交易")
    timestamp: str = Field("", description="交易时间")


class ExchangeStatus(BaseModel):
    """
    交易所状态模型

    记录单个交易所的连接状态和运行指标，用于系统监控。
    """
    name: str = Field(..., description="交易所名称")
    enabled: bool = Field(True, description="是否启用")
    connected: bool = Field(False, description="是否已连接")
    last_update: Optional[str] = Field(None, description="最后更新时间")
    error_count: int = Field(0, description="错误计数")
    latency_ms: float = Field(0.0, description="平均延迟（毫秒）")


class SystemConfig(BaseModel):
    """
    系统配置模型

    管理套利系统的全部运行参数，支持通过 API 动态修改。
    """
    exchanges: List[str] = Field(default_factory=list, description="启用的交易所列表")
    symbols: List[str] = Field(default_factory=list, description="监控的交易对列表")
    min_profitability: float = Field(0.003, description="最小净利润率（0.003 = 0.3%）")
    order_amount: float = Field(0.01, description="单笔下单量（基础货币）")
    scan_interval: int = Field(10, description="扫描间隔（秒）")
    max_order_age: int = Field(180, description="订单超时时间（秒）")
    paper_trade: bool = Field(True, description="是否模拟交易")
    fee_rate: float = Field(0.001, description="默认手续费率（0.001 = 0.1%）")
    exchange_fees: Dict[str, float] = Field(
        default_factory=dict, description="各交易所手续费率映射"
    )
    top_n_opportunities: int = Field(20, description="返回的最大机会数量")
