"""
回测引擎核心模块

基于历史 K 线数据模拟策略执行，计算策略在历史行情下的表现。

核心功能：
- 加载历史 K 线数据
- 逐根 K 线模拟策略信号生成与执行
- 滑点 + 手续费模拟
- 资金管理与仓位追踪
- 性能指标计算（总收益/胜率/夏普比率/最大回撤）

使用方法：
    engine = BacktestEngine(collector)
    result = await engine.run(
        strategy=grid_strategy,
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1h",
        initial_capital=10000,
    )
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .collector import HistoryCollector
from ..strategies.base import BaseStrategy, StrategySignal

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """回测交易记录"""
    timestamp: int
    symbol: str
    side: str
    price: float
    amount: float
    fee: float
    reason: str


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str
    symbol: str
    timeframe: str
    start_time: int
    end_time: int
    initial_capital: float
    final_capital: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    win_rate: float
    max_drawdown: float
    sharpe_ratio: float
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "initial_capital": round(self.initial_capital, 2),
            "final_capital": round(self.final_capital, 2),
            "total_return_pct": round(
                (self.final_capital - self.initial_capital) / self.initial_capital * 100, 2
            ),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "total_pnl": round(self.total_pnl, 2),
            "max_drawdown_pct": round(self.max_drawdown * 100, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "trades": [
                {
                    "timestamp": t.timestamp,
                    "side": t.side,
                    "price": t.price,
                    "amount": t.amount,
                    "fee": t.fee,
                    "reason": t.reason,
                }
                for t in self.trades
            ],
            "equity_curve": self.equity_curve,
        }


class BacktestEngine:
    """
    回测引擎

    逐根 K 线回放历史数据，模拟策略信号生成与执行，
    计算策略在历史行情下的表现指标。
    """

    def __init__(
        self,
        collector: HistoryCollector,
        fee_rate: float = 0.001,
        slippage: float = 0.0005,
    ) -> None:
        """
        初始化回测引擎

        Args:
            collector: 历史数据采集器（提供 K 线数据）
            fee_rate: 手续费率（默认 0.1%）
            slippage: 滑点率（默认 0.05%）
        """
        self.collector = collector
        self.fee_rate = fee_rate
        self.slippage = slippage

    async def run(
        self,
        strategy: BaseStrategy,
        exchange: str,
        symbol: str,
        timeframe: str = "1h",
        initial_capital: float = 10000,
        kline_limit: int = 2000,
    ) -> BacktestResult:
        """
        执行回测

        Args:
            strategy: 策略实例
            exchange: 交易所名称
            symbol: 交易对
            timeframe: K 线周期
            initial_capital: 初始资金（USDT）
            kline_limit: 回测使用的 K 线数量

        Returns:
            回测结果
        """
        logger.info(
            "开始回测: %s %s %s %s 初始资金 %.0f",
            strategy.name, exchange, symbol, timeframe, initial_capital,
        )

        # 加载历史 K 线
        klines = self.collector.get_klines(exchange, symbol, timeframe, kline_limit)
        if len(klines) < 10:
            logger.warning("K 线数据不足（%d 条），无法回测", len(klines))
            return BacktestResult(
                strategy_name=strategy.name, symbol=symbol, timeframe=timeframe,
                start_time=0, end_time=0, initial_capital=initial_capital,
                final_capital=initial_capital, total_trades=0,
                winning_trades=0, losing_trades=0, total_pnl=0,
                win_rate=0, max_drawdown=0, sharpe_ratio=0,
            )

        # 启动策略
        await strategy.start()

        # 回测状态
        capital = initial_capital
        position_amount = 0.0
        position_cost = 0.0
        trades: List[BacktestTrade] = []
        equity_curve: List[Dict[str, Any]] = []
        peak_equity = initial_capital
        max_drawdown = 0.0
        daily_returns: List[float] = []

        # 逐根 K 线回放
        for kline in klines:
            ts = kline["timestamp"]
            close_price = kline["close"]

            # 构造价格快照（模拟单交易所单交易对）
            prices = {
                exchange: {
                    symbol: {
                        "bid": close_price,
                        "ask": close_price,
                        "last": close_price,
                        "volume": kline["volume"],
                        "timestamp": ts,
                    }
                }
            }

            # 调用策略生成信号
            try:
                signals = await strategy.generate_signals(prices)
            except Exception as e:
                logger.debug("策略生成信号异常: %s", e)
                signals = []

            # 执行信号
            for signal in signals:
                if signal.symbol != symbol:
                    continue

                # 模拟滑点
                if signal.side == "buy":
                    exec_price = signal.price * (1 + self.slippage)
                else:
                    exec_price = signal.price * (1 - self.slippage)

                fee = exec_price * signal.amount * self.fee_rate

                if signal.side == "buy":
                    cost = exec_price * signal.amount + fee
                    if capital >= cost:
                        capital -= cost
                        position_amount += signal.amount
                        position_cost += cost
                        trades.append(BacktestTrade(
                            timestamp=ts, symbol=symbol, side="buy",
                            price=exec_price, amount=signal.amount,
                            fee=fee, reason=signal.reason,
                        ))
                elif signal.side == "sell":
                    sell_amount = min(signal.amount, position_amount)
                    if sell_amount > 0:
                        revenue = exec_price * sell_amount - fee
                        capital += revenue
                        # 计算这笔卖出的盈亏
                        avg_cost = position_cost / position_amount if position_amount > 0 else 0
                        pnl = (exec_price - avg_cost) * sell_amount - fee
                        position_amount -= sell_amount
                        position_cost = avg_cost * position_amount
                        trades.append(BacktestTrade(
                            timestamp=ts, symbol=symbol, side="sell",
                            price=exec_price, amount=sell_amount,
                            fee=fee, reason=signal.reason,
                        ))

            # 计算当前权益
            equity = capital + position_amount * close_price
            equity_curve.append({"timestamp": ts, "equity": round(equity, 2)})

            # 更新最大回撤
            if equity > peak_equity:
                peak_equity = equity
            drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
            if drawdown > max_drawdown:
                max_drawdown = drawdown

            # 记录日收益率（简化：每根 K 线一个点）
            if len(equity_curve) >= 2:
                prev_equity = equity_curve[-2]["equity"]
                if prev_equity > 0:
                    daily_returns.append((equity - prev_equity) / prev_equity)

        # 停止策略
        await strategy.stop()

        # 计算最终结果
        final_capital = capital + position_amount * klines[-1]["close"]
        total_pnl = final_capital - initial_capital

        # 统计交易
        sell_trades = [t for t in trades if t.side == "sell"]
        winning = sum(1 for t in sell_trades if t.price > position_cost / max(position_amount, 1))
        total_sell = len(sell_trades)

        # 夏普比率（简化计算）
        sharpe = 0.0
        if len(daily_returns) > 1:
            avg_return = sum(daily_returns) / len(daily_returns)
            variance = sum((r - avg_return) ** 2 for r in daily_returns) / len(daily_returns)
            std = math.sqrt(variance)
            if std > 0:
                sharpe = avg_return / std * math.sqrt(252)

        result = BacktestResult(
            strategy_name=strategy.name,
            symbol=symbol,
            timeframe=timeframe,
            start_time=klines[0]["timestamp"],
            end_time=klines[-1]["timestamp"],
            initial_capital=initial_capital,
            final_capital=final_capital,
            total_trades=len(trades),
            winning_trades=winning,
            losing_trades=total_sell - winning,
            total_pnl=total_pnl,
            win_rate=winning / total_sell if total_sell > 0 else 0,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            trades=trades,
            equity_curve=equity_curve,
        )

        logger.info(
            "回测完成: %s 总交易 %d 胜率 %.1f%% 收益 %.2f 回撤 %.2f%% 夏普 %.2f",
            strategy.name, result.total_trades, result.win_rate * 100,
            result.total_pnl, result.max_drawdown * 100, result.sharpe_ratio,
        )

        return result

        return result


class ParamSweep:
    """参数扫描器：对策略进行多参数组合回测"""

    def __init__(self, engine: BacktestEngine) -> None:
        self.engine = engine

    async def sweep(
        self,
        strategy_factory,
        exchange: str,
        symbol: str,
        param_grid: Dict[str, List[Any]],
        timeframe: str = "1h",
        initial_capital: float = 10000,
        kline_limit: int = 2000,
    ) -> List[Dict[str, Any]]:
        """
        执行参数扫描

        Args:
            strategy_factory: 接受参数字典返回策略实例的工厂函数
            exchange: 交易所名称
            symbol: 交易对
            param_grid: 参数网格 {param_name: [val1, val2, ...]}
            timeframe: K线周期
            initial_capital: 初始资金
            kline_limit: K线数量

        Returns:
            每组参数的回测结果列表
        """
        import itertools

        # 生成所有参数组合
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        combinations = list(itertools.product(*values))

        results: List[Dict[str, Any]] = []
        logger.info("参数扫描: %d 组参数组合", len(combinations))

        for i, combo in enumerate(combinations):
            params = dict(zip(keys, combo))
            strategy = strategy_factory(params)
            result = await self.engine.run(
                strategy=strategy,
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                initial_capital=initial_capital,
                kline_limit=kline_limit,
            )
            result_dict = result.to_dict()
            result_dict["params"] = params
            results.append(result_dict)

            logger.info(
                "参数扫描 %d/%d: %s 收益=%.2f 胜率=%.1f%%",
                i + 1, len(combinations), params,
                result.total_pnl, result.win_rate * 100,
            )

        # 按收益排序
        results.sort(key=lambda x: x["total_pnl"], reverse=True)
        return results

    def export_report(
        self, results: List[Dict[str, Any]], output_path: str
    ) -> None:
        """导出参数扫描报告为 Markdown"""
        from pathlib import Path

        lines = ["# 参数扫描报告", ""]
        lines.append(f"共 {len(results)} 组参数组合，按收益排序：")
        lines.append("")
        lines.append("| 排名 | 参数 | 收益(USDT) | 收益率 | 胜率 | 最大回撤 | 夏普 |")
        lines.append("|------|------|-----------|--------|------|---------|------|")

        for i, r in enumerate(results[:20], 1):
            lines.append(
                f"| {i} | {r['params']} | {r['total_pnl']:.2f} | "
                f"{r['total_return_pct']:.2f}% | {r['win_rate']:.1%} | "
                f"{r['max_drawdown_pct']:.2f}% | {r['sharpe_ratio']:.2f} |"
            )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write("\n".join(lines))
        logger.info("参数扫描报告已导出: %s", output_path)
