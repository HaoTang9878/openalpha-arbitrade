"""
套利检测引擎模块

基于 Hummingbot 的套利策略逻辑，检测跨交易所套利机会。

核心算法（参考 Hummingbot arbitrage_strategy.pyx）：
1. 获取两个交易所的订单簿价格
2. 计算两个方向的套利提案（A->B 和 B->A）
3. 计算净利润率 = (卖出收入 - 买入成本 - 双边手续费) / 买入成本
4. 若净利润率 >= min_profitability，则标记为套利机会
5. 选择利润更高的方向执行

关键改进：
- 同时扫描 N 个交易所（不只是两个）
- 对每个交易对找出价差最大的交易所对
- 考虑手续费、滑点估算
- 根据价差大小和交易量评估风险等级

使用方法：
    detector = ArbitrageDetector(config)
    opportunities = detector.detect(prices_snapshot)
"""

import logging
import time
from typing import Any, Dict, List

from .config import Config
from .models import ArbitrageOpportunity, RiskLevel

logger = logging.getLogger(__name__)

# 风险等级阈值（基于价差百分比）
RISK_HIGH_THRESHOLD = 0.02    # 价差 > 2% 视为高风险
RISK_MEDIUM_THRESHOLD = 0.01  # 价差 1%-2% 视为中等风险

# 滑点估算系数（基于订单量的价格影响比例）
SLIPPAGE_FACTOR = 0.0002      # 0.02% 估算滑点（小单量）


class ArbitrageDetector:
    """
    套利检测引擎

    从价格快照中分析各交易对的跨交易所价差，
    找出净利润率最高的套利机会。
    """

    def __init__(self, config: Config) -> None:
        """
        初始化套利检测引擎

        Args:
            config: 系统配置管理器
        """
        self.config = config

    def detect(
        self, prices: Dict[str, Dict[str, Dict[str, Any]]]
    ) -> List[ArbitrageOpportunity]:
        """
        从价格快照中检测套利机会

        对每个交易对，找出 ask 最低的交易所（买入）和 bid 最高的交易所（卖出），
        计算净利润率并过滤不满足条件的机会。

        Args:
            prices: 价格快照，格式为
                    {exchange: {symbol: {bid, ask, last, volume, timestamp}}}

        Returns:
            套利机会列表，按净利润率降序排列，最多返回 top_n 条
        """
        if not prices:
            logger.debug("价格快照为空，跳过检测")
            return []

        opportunities: List[ArbitrageOpportunity] = []
        min_profit = self.config.model.min_profitability
        order_amount = self.config.model.order_amount
        current_ts = int(time.time() * 1000)

        # 遍历每个交易对，寻找最佳套利机会
        for symbol in self.config.model.symbols:
            opportunity = self._detect_symbol_opportunity(
                symbol, prices, min_profit, order_amount, current_ts
            )
            if opportunity:
                opportunities.append(opportunity)

        # 按净利润率降序排列
        opportunities.sort(key=lambda x: x.net_profit_rate, reverse=True)

        # 返回 Top N 机会
        top_n = self.config.model.top_n_opportunities
        result = opportunities[:top_n]

        if result:
            logger.info("检测到 %d 个套利机会（共扫描 %d 个交易对）",
                        len(result), len(self.config.model.symbols))

        return result

    def _detect_symbol_opportunity(
        self,
        symbol: str,
        prices: Dict[str, Dict[str, Dict[str, Any]]],
        min_profit: float,
        order_amount: float,
        timestamp: int,
    ) -> ArbitrageOpportunity:
        """
        检测单个交易对的最佳套利机会

        在所有交易所中找出 ask 最低（买入最优）和 bid 最高（卖出最优）的交易所，
        计算价差和净利润率。

        Args:
            symbol: 交易对
            prices: 完整价格快照
            min_profit: 最小净利润率阈值
            order_amount: 下单量
            timestamp: 当前时间戳

        Returns:
            套利机会对象，若无有效机会则返回 None
        """
        best_buy = None  # (exchange_name, ask_price)
        best_sell = None  # (exchange_name, bid_price)

        # 遍历所有交易所，找出最优买价和卖价
        for ex_name, exchange_prices in prices.items():
            ticker = exchange_prices.get(symbol)
            if not ticker:
                continue

            ask = ticker.get("ask", 0)
            bid = ticker.get("bid", 0)

            if ask <= 0 or bid <= 0:
                continue

            # 寻找最低卖价（买入成本最低）
            if best_buy is None or ask < best_buy[1]:
                best_buy = (ex_name, ask)

            # 寻找最高买价（卖出收入最高）
            if best_sell is None or bid > best_sell[1]:
                best_sell = (ex_name, bid)

        # 必须在不同交易所才有套利意义
        if not best_buy or not best_sell:
            return None
        if best_buy[0] == best_sell[0]:
            return None

        buy_exchange, buy_price = best_buy
        sell_exchange, sell_price = best_sell

        # 计算原始价差百分比
        spread_percent = (sell_price - buy_price) / buy_price

        # 计算净利润率（扣除双边手续费和估算滑点）
        buy_fee = self.config.get_exchange_fee(buy_exchange)
        sell_fee = self.config.get_exchange_fee(sell_exchange)
        total_fee = buy_fee + sell_fee
        net_profit_rate = spread_percent - total_fee - SLIPPAGE_FACTOR

        # 过滤不满足最小利润率的机会
        if net_profit_rate < min_profit:
            return None

        # 计算预计净利润（以 USDT 计）
        estimated_profit = net_profit_rate * buy_price * order_amount

        # 评估风险等级
        risk_level = self._assess_risk(spread_percent, prices, symbol)

        logger.debug(
            "发现套利机会: %s 买入@%s(%.4f) 卖出@%s(%.4f) "
            "净利润率=%.4f%% 预计利润=%.4f USDT",
            symbol, buy_exchange, buy_price,
            sell_exchange, sell_price,
            net_profit_rate * 100, estimated_profit,
        )

        return ArbitrageOpportunity(
            symbol=symbol,
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            buy_price=buy_price,
            sell_price=sell_price,
            spread_percent=spread_percent,
            net_profit_rate=net_profit_rate,
            estimated_profit=estimated_profit,
            risk_level=risk_level,
            timestamp=timestamp,
        )

    def _assess_risk(
        self,
        spread_percent: float,
        prices: Dict[str, Dict[str, Dict[str, Any]]],
        symbol: str,
    ) -> RiskLevel:
        """
        评估套利机会的风险等级

        风险评估基于两个因素：
        1. 价差大小：价差越大，价格回归风险越高
        2. 交易量：交易量越低，流动性风险越高

        Args:
            spread_percent: 原始价差百分比
            prices: 价格快照
            symbol: 交易对

        Returns:
            风险等级枚举值
        """
        # 价差越大风险越高（可能是市场异常或数据延迟）
        if spread_percent > RISK_HIGH_THRESHOLD:
            return RiskLevel.HIGH
        if spread_percent > RISK_MEDIUM_THRESHOLD:
            return RiskLevel.MEDIUM

        # 检查交易量，低交易量意味着流动性风险
        total_volume = 0.0
        volume_count = 0
        for exchange_prices in prices.values():
            ticker = exchange_prices.get(symbol)
            if ticker and ticker.get("volume", 0) > 0:
                total_volume += ticker["volume"]
                volume_count += 1

        # 平均交易量低于阈值视为高风险
        if volume_count > 0:
            avg_volume = total_volume / volume_count
            if avg_volume < 100000:  # 10万 USDT 以下视为低流动性
                return RiskLevel.HIGH

        return RiskLevel.LOW
