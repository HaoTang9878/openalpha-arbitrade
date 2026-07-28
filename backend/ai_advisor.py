"""
AI 策略推荐模块

基于市场数据分析，自动推荐最适合当前行情的交易策略组合。

核心功能：
- 市场状态识别（趋势/震荡/高波动）
- 基于波动率和趋势指标推荐策略
- 策略组合优化（资金分配建议）
- 风险偏好匹配

推荐逻辑：
- 震荡行情 → 网格策略（低波动率 + 横盘）
- 趋势上涨 → DCA 策略（回调买入）
- 高波动 → 跨所套利（价差大）
- 低波动 → 三角套利（同所内微利）

使用方法：
    advisor = AIAdvisor()
    recommendation = advisor.analyze(prices, capital=10000, risk_tolerance="medium")
"""

import logging
import math
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class AIAdvisor:
    """
    AI 策略推荐器

    分析市场数据，推荐最优策略组合。
    """

    def __init__(self) -> None:
        """初始化 AI 推荐器"""
        # 波动率阈值
        self.low_volatility = 0.01    # < 1% 低波动
        self.high_volatility = 0.03   # > 3% 高波动
        # 趋势阈值
        self.trend_threshold = 0.005  # 0.5% 视为趋势

    def analyze(
        self,
        prices: Dict[str, Dict[str, Dict[str, Any]]],
        capital: float = 10000,
        risk_tolerance: str = "medium",
    ) -> Dict[str, Any]:
        """
        分析市场并推荐策略组合

        Args:
            prices: 价格快照
            capital: 可用资金（USDT）
            risk_tolerance: 风险偏好（low/medium/high）

        Returns:
            推荐结果 {market_state, recommendations, allocation}
        """
        # 1. 市场状态分析
        market_state = self._analyze_market(prices)

        # 2. 策略推荐
        recommendations = self._recommend_strategies(market_state, risk_tolerance)

        # 3. 资金分配
        allocation = self._allocate_capital(recommendations, capital, risk_tolerance)

        result = {
            "market_state": market_state,
            "risk_tolerance": risk_tolerance,
            "capital": capital,
            "recommendations": recommendations,
            "allocation": allocation,
            "summary": self._generate_summary(market_state, recommendations),
        }

        logger.info(
            "AI推荐完成: 市场状态=%s 推荐%d个策略",
            market_state["state"], len(recommendations),
        )
        return result

    def _analyze_market(
        self, prices: Dict[str, Dict[str, Dict[str, Any]]]
    ) -> Dict[str, Any]:
        """
        分析市场状态

        计算整体波动率、趋势方向和流动性。

        Args:
            prices: 价格快照

        Returns:
            市场状态字典 {state, volatility, trend, liquidity}
        """
        spreads: List[float] = []
        volumes: List[float] = []
        price_changes: List[float] = []

        for exchange, symbols in prices.items():
            for symbol, ticker in symbols.items():
                bid = ticker.get("bid", 0)
                ask = ticker.get("ask", 0)
                last = ticker.get("last", 0)
                volume = ticker.get("volume", 0)

                if bid > 0 and ask > 0:
                    # 买卖价差作为波动率代理
                    spread = (ask - bid) / bid
                    spreads.append(spread)

                if volume > 0:
                    volumes.append(volume)

                if last > 0 and bid > 0:
                    # last vs mid 偏离作为趋势代理
                    mid = (bid + ask) / 2
                    if mid > 0:
                        price_changes.append((last - mid) / mid)

        # 计算统计量
        avg_spread = sum(spreads) / len(spreads) if spreads else 0
        avg_volume = sum(volumes) / len(volumes) if volumes else 0
        avg_change = sum(price_changes) / len(price_changes) if price_changes else 0

        # 判断市场状态
        if avg_spread < self.low_volatility:
            state = "ranging"  # 震荡
        elif avg_spread > self.high_volatility:
            state = "volatile"  # 高波动
        elif abs(avg_change) > self.trend_threshold:
            state = "trending_up" if avg_change > 0 else "trending_down"
        else:
            state = "neutral"

        # 流动性评估
        if avg_volume > 100000000:  # 1亿 USDT
            liquidity = "high"
        elif avg_volume > 10000000:  # 1千万
            liquidity = "medium"
        else:
            liquidity = "low"

        return {
            "state": state,
            "volatility": round(avg_spread, 6),
            "volatility_pct": round(avg_spread * 100, 4),
            "trend": round(avg_change, 6),
            "trend_pct": round(avg_change * 100, 4),
            "liquidity": liquidity,
            "avg_volume": round(avg_volume, 2),
            "symbols_analyzed": len(spreads),
        }

    def _recommend_strategies(
        self, market_state: Dict[str, Any], risk_tolerance: str
    ) -> List[Dict[str, Any]]:
        """
        基于市场状态推荐策略

        Args:
            market_state: 市场状态
            risk_tolerance: 风险偏好

        Returns:
            策略推荐列表
        """
        state = market_state["state"]
        recommendations: List[Dict[str, Any]] = []

        # 策略推荐矩阵
        strategy_map = {
            "ranging": [
                {"type": "grid", "priority": "high", "reason": "震荡行情适合网格低买高卖"},
                {"type": "triangular", "priority": "medium", "reason": "低波动期三角套利机会稳定"},
            ],
            "trending_up": [
                {"type": "dca", "priority": "high", "reason": "上涨趋势回调买入降低成本"},
                {"type": "arbitrage", "priority": "medium", "reason": "趋势行情跨所价差扩大"},
            ],
            "trending_down": [
                {"type": "dca", "priority": "medium", "reason": "下跌分批买入等待反弹"},
                {"type": "arbitrage", "priority": "high", "reason": "恐慌行情跨所价差最大"},
            ],
            "volatile": [
                {"type": "arbitrage", "priority": "high", "reason": "高波动期跨所套利利润最大"},
                {"type": "grid", "priority": "medium", "reason": "宽幅震荡网格利润丰厚"},
            ],
            "neutral": [
                {"type": "grid", "priority": "medium", "reason": "中性行情网格稳健"},
                {"type": "arbitrage", "priority": "medium", "reason": "常规跨所套利"},
            ],
        }

        base_recs = strategy_map.get(state, strategy_map["neutral"])

        # 根据风险偏好调整
        for rec in base_recs:
            if risk_tolerance == "low" and rec["type"] in ("triangular",):
                continue  # 低风险偏好跳过三角套利
            if risk_tolerance == "high" and rec["type"] == "grid":
                rec["priority"] = "medium"  # 高风险偏好降低网格优先级

            recommendations.append({
                "strategy_type": rec["type"],
                "priority": rec["priority"],
                "reason": rec["reason"],
                "expected_risk": self._strategy_risk(rec["type"]),
                "expected_return": self._strategy_return(rec["type"], market_state),
            })

        # 按优先级排序
        priority_order = {"high": 0, "medium": 1, "low": 2}
        recommendations.sort(key=lambda x: priority_order.get(x["priority"], 3))

        return recommendations

    def _strategy_risk(self, strategy_type: str) -> str:
        """策略风险等级"""
        risk_map = {
            "grid": "low",
            "dca": "medium",
            "arbitrage": "low",
            "triangular": "medium",
        }
        return risk_map.get(strategy_type, "medium")

    def _strategy_return(
        self, strategy_type: str, market_state: Dict[str, Any]
    ) -> str:
        """策略预期收益"""
        vol = market_state.get("volatility_pct", 0)
        return_map = {
            "grid": f"月化 {min(vol * 30, 5):.1f}%",
            "dca": "月化 2-8%（取决于趋势）",
            "arbitrage": f"月化 {min(vol * 50, 3):.1f}%",
            "triangular": "月化 1-3%",
        }
        return return_map.get(strategy_type, "月化 2-5%")

    def _allocate_capital(
        self,
        recommendations: List[Dict[str, Any]],
        capital: float,
        risk_tolerance: str,
    ) -> List[Dict[str, Any]]:
        """
        资金分配建议

        Args:
            recommendations: 策略推荐列表
            capital: 总资金
            risk_tolerance: 风险偏好

        Returns:
            资金分配列表
        """
        if not recommendations:
            return []

        # 按优先级分配权重
        priority_weights = {"high": 0.5, "medium": 0.3, "low": 0.2}
        total_weight = sum(
            priority_weights.get(r["priority"], 0.1) for r in recommendations
        )

        allocation = []
        for rec in recommendations:
            weight = priority_weights.get(rec["priority"], 0.1) / total_weight
            amount = capital * weight
            allocation.append({
                "strategy_type": rec["strategy_type"],
                "weight": round(weight, 4),
                "amount_usdt": round(amount, 2),
                "priority": rec["priority"],
            })

        return allocation

    def _generate_summary(
        self,
        market_state: Dict[str, Any],
        recommendations: List[Dict[str, Any]],
    ) -> str:
        """生成推荐摘要"""
        state_names = {
            "ranging": "震荡",
            "trending_up": "上涨趋势",
            "trending_down": "下跌趋势",
            "volatile": "高波动",
            "neutral": "中性",
        }
        state_name = state_names.get(market_state["state"], market_state["state"])
        top_strategy = recommendations[0]["strategy_type"] if recommendations else "无"

        strategy_names = {
            "grid": "网格交易",
            "dca": "DCA定投",
            "arbitrage": "跨所套利",
            "triangular": "三角套利",
        }
        top_name = strategy_names.get(top_strategy, top_strategy)

        return (
            f"当前市场为{state_name}行情（波动率{market_state['volatility_pct']:.3f}%），"
            f"推荐以{top_name}为主策略，"
            f"共{len(recommendations)}个策略组合。"
        )
