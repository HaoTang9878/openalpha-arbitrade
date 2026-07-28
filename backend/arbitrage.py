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
from typing import Any, Dict, List, Optional, Tuple

from .config import Config
from .models import ArbitrageOpportunity, RiskLevel

logger = logging.getLogger(__name__)

# 风险等级阈值（基于价差百分比）
RISK_HIGH_THRESHOLD = 0.02    # 价差 > 2% 视为高风险
RISK_MEDIUM_THRESHOLD = 0.01  # 价差 1%-2% 视为中等风险

# 无 L2 订单簿数据时的回退固定滑点（小单量估算）
FALLBACK_SLIPPAGE = 0.0002    # 0.02%

# 订单簿深度不足时的滑点惩罚
INSUFFICIENT_DEPTH_SLIPPAGE = 0.01  # 1%

# 动态滑点计算时最多查看的订单簿档位数
MAX_ORDERBOOK_LEVELS = 10


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
        self,
        prices: Dict[str, Dict[str, Dict[str, Any]]],
        orderbooks: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None,
    ) -> List[ArbitrageOpportunity]:
        """
        从价格快照中检测套利机会

        对每个交易对，找出 ask 最低的交易所（买入）和 bid 最高的交易所（卖出），
        计算净利润率并过滤不满足条件的机会。

        Args:
            prices: 价格快照，格式为
                    {exchange: {symbol: {bid, ask, last, volume, timestamp}}}
            orderbooks: L2 订单簿缓存，格式为
                        {exchange: {symbol: {"bids": [[price, qty],...],
                                              "asks": [[price, qty],...]}}}
                        用于动态滑点计算，无数据时回退到固定滑点

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
                symbol, prices, orderbooks,
                min_profit, order_amount, current_ts,
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

    def _calculate_effective_price(
        self,
        orderbook: Optional[Dict[str, Any]],
        side: str,
        amount: float,
    ) -> Tuple[Optional[float], float]:
        """
        基于 L2 订单簿计算实际成交价和滑点

        模拟吃单（taker）行为：按订单簿深度逐档成交，直到满足下单量。
        实际成交价 = 加权平均成交价，滑点 = 相对最优价的偏离比例。

        Args:
            orderbook: {"bids": [[price, qty],...], "asks": [[price, qty],...]}
            side: "buy" 或 "sell"
                - "buy" 吃 ask 盘（卖方挂单）
                - "sell" 吃 bid 盘（买方挂单）
            amount: 下单数量（基础货币，如 BTC 数量）

        Returns:
            (effective_price, slippage_percent)
            - 无订单簿数据时返回 (None, FALLBACK_SLIPPAGE) 回退到固定滑点
            - 订单簿深度不足时返回 (最差档价, INSUFFICIENT_DEPTH_SLIPPAGE)
        """
        if not orderbook:
            return None, FALLBACK_SLIPPAGE  # 回退：固定 0.02%

        if side == "buy":
            levels = orderbook.get("asks", [])
        else:
            levels = orderbook.get("bids", [])

        if not levels:
            return None, FALLBACK_SLIPPAGE

        # 模拟吃单：按订单簿深度逐档成交
        remaining = amount
        total_cost = 0.0
        best_price = levels[0][0]

        for price, qty in levels[:MAX_ORDERBOOK_LEVELS]:  # 最多看 10 档
            if remaining <= 0:
                break
            fill = min(remaining, qty)
            total_cost += fill * price
            remaining -= fill

        if remaining > 0:
            # 订单簿深度不足，无法完全成交，返回悲观值
            return levels[-1][0], INSUFFICIENT_DEPTH_SLIPPAGE  # 1% 滑点惩罚

        effective_price = total_cost / amount
        if side == "buy":
            slippage = (effective_price - best_price) / best_price
        else:
            slippage = (best_price - effective_price) / best_price

        return effective_price, slippage

    def _detect_symbol_opportunity(
        self,
        symbol: str,
        prices: Dict[str, Dict[str, Dict[str, Any]]],
        orderbooks: Optional[Dict[str, Dict[str, Dict[str, Any]]]],
        min_profit: float,
        order_amount: float,
        timestamp: int,
    ) -> ArbitrageOpportunity:
        """
        检测单个交易对的最佳套利机会

        在所有交易所中找出 ask 最低（买入最优）和 bid 最高（卖出最优）的交易所，
        计算价差和净利润率。优先使用 L2 订单簿计算实际成交价和动态滑点，
        无 L2 数据时回退到 ticker top-1 价 + 固定滑点。

        Args:
            symbol: 交易对
            prices: 完整价格快照
            orderbooks: L2 订单簿缓存（可为 None）
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

        # 计算原始价差百分比（基于 ticker top-1 价）
        spread_percent = (sell_price - buy_price) / buy_price

        # 计算双边手续费
        buy_fee = self.config.get_exchange_fee(buy_exchange)
        sell_fee = self.config.get_exchange_fee(sell_exchange)
        total_fee = buy_fee + sell_fee

        # 优先使用 L2 订单簿计算实际成交价和动态滑点
        buy_ob = (
            orderbooks.get(buy_exchange, {}).get(symbol)
            if orderbooks else None
        )
        sell_ob = (
            orderbooks.get(sell_exchange, {}).get(symbol)
            if orderbooks else None
        )

        eff_buy_price, buy_slippage = self._calculate_effective_price(
            buy_ob, "buy", order_amount
        )
        eff_sell_price, sell_slippage = self._calculate_effective_price(
            sell_ob, "sell", order_amount
        )

        if eff_buy_price is not None and eff_sell_price is not None:
            # 有 L2 数据：用实际成交价计算净利润率（滑点已体现在成交价中）
            actual_spread = (eff_sell_price - eff_buy_price) / eff_buy_price
            net_profit_rate = actual_spread - total_fee
            logger.debug(
                "%s L2 成交价: 买入=%.4f(滑点=%.4f%%) 卖出=%.4f(滑点=%.4f%%) "
                "实际价差=%.4f%%",
                symbol, eff_buy_price, buy_slippage * 100,
                eff_sell_price, sell_slippage * 100,
                actual_spread * 100,
            )
        else:
            # 无 L2 数据：回退到 ticker top-1 价 + 固定滑点
            net_profit_rate = (
                spread_percent - total_fee - FALLBACK_SLIPPAGE
            )
            logger.debug(
                "%s 无 L2 数据，回退固定滑点: 价差=%.4f%% 净利润率=%.4f%%",
                symbol, spread_percent * 100, net_profit_rate * 100,
            )

        # 安全护栏：净利润率必须为正，即使配置允许负值也拒绝
        HARD_MIN_PROFIT = 0.0  # 硬性下限：0%（不允许亏钱）
        if net_profit_rate < max(min_profit, HARD_MIN_PROFIT):
            return None

        # 计算预计净利润（以 USDT 计）
        estimated_profit = net_profit_rate * buy_price * order_amount

        # 评估风险等级（数值化评分 0-100）
        risk_score, risk_level = self._assess_risk(spread_percent, prices, symbol)

        logger.debug(
            "发现套利机会: %s 买入@%s(%.4f) 卖出@%s(%.4f) "
            "净利润率=%.4f%% 预计利润=%.4f USDT 风险评分=%.1f",
            symbol, buy_exchange, buy_price,
            sell_exchange, sell_price,
            net_profit_rate * 100, estimated_profit, risk_score,
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
            risk_score=risk_score,
            timestamp=timestamp,
        )

    def _calculate_risk_score(
        self,
        spread_percent: float,
        prices: Dict[str, Dict[str, Dict[str, Any]]],
        symbol: str,
    ) -> Tuple[float, RiskLevel]:
        """
        多维度数值化风险评分（0-100，越低越安全）

        评分维度（各占权重）：
        1. 价差异常度（35%）：价差越偏离历史均值，风险越高
           - < 0.5% → 低风险（0-20 分）
           - 0.5%-1% → 中风险（20-50 分）
           - 1%-2% → 高风险（50-80 分）
           - > 2% → 极高风险（80-100 分）
        2. 流动性风险（30%）：交易量越低，执行风险越高
           - > 1 亿 USDT → 0-10 分
           - 1000 万-1 亿 → 10-30 分
           - < 1000 万 → 30-60 分
        3. 净利润率稳健度（20%）：利润率越接近阈值，越脆弱
           - > 0.5% → 0-15 分
           - 0.1%-0.5% → 15-40 分
           - < 0.1% → 40-60 分
        4. 交易所数量（15%）：参与交易所越少，集中度风险越高
           - ≥ 4 所 → 0-10 分
           - 2-3 所 → 10-30 分

        Args:
            spread_percent: 原始价差百分比（小数，如 0.005 = 0.5%）
            prices: 价格快照
            symbol: 交易对

        Returns:
            (risk_score 0-100, risk_level 枚举)
        """
        spread_pct = spread_percent * 100  # 转为百分比

        # 1. 价差异常度评分（35%权重）
        if spread_pct < 0.5:
            spread_score = spread_pct / 0.5 * 20
        elif spread_pct < 1.0:
            spread_score = 20 + (spread_pct - 0.5) / 0.5 * 30
        elif spread_pct < 2.0:
            spread_score = 50 + (spread_pct - 1.0) / 1.0 * 30
        else:
            spread_score = min(80 + (spread_pct - 2.0) * 10, 100)
        spread_score *= 0.35

        # 2. 流动性风险评分（30%权重）
        total_volume = 0.0
        volume_count = 0
        for exchange_prices in prices.values():
            ticker = exchange_prices.get(symbol)
            if ticker and ticker.get("volume", 0) > 0:
                total_volume += ticker["volume"]
                volume_count += 1

        avg_volume = total_volume / volume_count if volume_count > 0 else 0
        if avg_volume > 100_000_000:  # > 1 亿
            liquidity_score = min(avg_volume / 1_000_000_000 * 10, 10)
        elif avg_volume > 10_000_000:  # > 1000 万
            liquidity_score = 10 + (100_000_000 - avg_volume) / 90_000_000 * 20
        else:  # < 1000 万
            liquidity_score = 30 + min((10_000_000 - avg_volume) / 10_000_000 * 30, 30)
        liquidity_score *= 0.30

        # 3. 净利润率稳健度（20%权重）
        total_fee = 0.002  # 双边手续费默认
        net_rate_pct = spread_pct - total_fee * 100
        if net_rate_pct > 0.5:
            profit_score = min(net_rate_pct / 0.5 * 15, 15)
        elif net_rate_pct > 0.1:
            profit_score = 15 + (0.5 - net_rate_pct) / 0.4 * 25
        else:
            profit_score = 40 + min((0.1 - net_rate_pct) / 0.1 * 20, 20)
        profit_score *= 0.20

        # 4. 交易所集中度（15%权重）
        exchange_count = len(prices)
        if exchange_count >= 4:
            concentration_score = min(exchange_count * 2.5, 10)
        else:
            concentration_score = 10 + (4 - exchange_count) * 10
        concentration_score *= 0.15

        # 综合评分
        risk_score = spread_score + liquidity_score + profit_score + concentration_score
        risk_score = max(0, min(100, risk_score))

        # 映射到风险等级
        if risk_score >= 60:
            risk_level = RiskLevel.HIGH
        elif risk_score >= 30:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW

        return round(risk_score, 1), risk_level

    def _assess_risk(
        self,
        spread_percent: float,
        prices: Dict[str, Dict[str, Dict[str, Any]]],
        symbol: str,
    ) -> Tuple[float, RiskLevel]:
        """
        评估套利机会的风险等级（委托给 _calculate_risk_score）

        Args:
            spread_percent: 原始价差百分比
            prices: 价格快照
            symbol: 交易对

        Returns:
            (risk_score 0-100, risk_level 枚举)
        """
        return self._calculate_risk_score(spread_percent, prices, symbol)
