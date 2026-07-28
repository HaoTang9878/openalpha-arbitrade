/**
 * Backtest 页面 — 回测引擎
 *
 * 支持下载历史 K 线数据、配置策略参数、执行回测，
 * 并可视化回测结果（K 线图 + 权益曲线 + 交易统计）。
 */

import { useState, useEffect } from 'react';
import { api } from '../api/client';
import { KlineChart } from '../components/charts/KlineChart';
import { toast } from '../components/common/Toast';
import { Skeleton } from '../components/common/Skeleton';
import { EmptyState } from '../components/common/EmptyState';
import { formatUsdt } from '../utils/format';

/** K 线数据类型 */
interface KlineData {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface BacktestResultData {
  strategy_name: string;
  symbol: string;
  timeframe: string;
  initial_capital: number;
  final_capital: number;
  total_return_pct: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  equity_curve: Array<{ timestamp: number; equity: number }>;
}

export function Backtest() {
  const [klines, setKlines] = useState<KlineData[]>([]);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [result, setResult] = useState<BacktestResultData | null>(null);
  const [running, setRunning] = useState(false);

  // 回测参数
  const [exchange, setExchange] = useState('binance');
  const [symbol, setSymbol] = useState('BTC/USDT');
  const [timeframe, setTimeframe] = useState('1h');
  const [days, setDays] = useState(7);
  const [strategyType, setStrategyType] = useState('grid');
  const [capital, setCapital] = useState(10000);

  /** 加载已存储的 K 线数据 */
  const loadKlines = async () => {
    setLoading(true);
    try {
      const data = await api.getKlines(exchange, symbol, timeframe, 500);
      setKlines(data.klines || []);
    } catch (e) {
      toast.error('加载 K 线失败');
    } finally {
      setLoading(false);
    }
  };

  /** 下载历史数据 */
  const handleDownload = async () => {
    setDownloading(true);
    try {
      const data = await api.downloadKlines(exchange, symbol, timeframe, days);
      toast.success(`已下载 ${data.downloaded} 条 K 线数据`);
      await loadKlines();
    } catch (e) {
      toast.error('下载失败: ' + (e as Error).message);
    } finally {
      setDownloading(false);
    }
  };

  /** 运行回测 */
  const handleRunBacktest = async () => {
    if (klines.length < 10) {
      toast.warning('K 线数据不足，请先下载历史数据');
      return;
    }
    setRunning(true);
    try {
      const config: Record<string, unknown> = {
        symbol,
        exchange,
        lower_price: 60000,
        upper_price: 70000,
        grid_count: 10,
        total_investment: capital,
      };
      const data = await api.runBacktest(
        strategyType, config, exchange, symbol, timeframe, capital,
      ) as unknown as BacktestResultData;
      setResult(data);
      toast.success(`回测完成: ${data.total_trades} 笔交易, 收益 ${formatUsdt(data.total_pnl)}`);
    } catch (e) {
      toast.error('回测失败: ' + (e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  useEffect(() => {
    loadKlines();
  }, [exchange, symbol, timeframe]);

  return (
    <div className="p-4 overflow-y-auto flex flex-col gap-3">
      <div className="mb-2">
        <h2 className="text-lg font-bold mb-1">策略回测</h2>
        <p className="text-xs text-muted">用历史数据验证策略表现</p>
      </div>

      {/* 参数配置面板 */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">回测配置</span>
        </div>
        <div className="p-3.5 grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <label className="text-xs text-muted block mb-1">交易所</label>
            <select value={exchange} onChange={(e) => setExchange(e.target.value)} className="input w-full">
              {['binance', 'okx', 'bybit', 'gate', 'kucoin'].map((ex) => (
                <option key={ex} value={ex}>{ex}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted block mb-1">交易对</label>
            <input value={symbol} onChange={(e) => setSymbol(e.target.value)} className="input w-full" />
          </div>
          <div>
            <label className="text-xs text-muted block mb-1">时间周期</label>
            <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)} className="input w-full">
              {['1m', '5m', '15m', '1h', '4h', '1d'].map((tf) => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted block mb-1">历史天数</label>
            <input type="number" value={days} onChange={(e) => setDays(parseInt(e.target.value))} className="input w-full" />
          </div>
          <div>
            <label className="text-xs text-muted block mb-1">策略类型</label>
            <select value={strategyType} onChange={(e) => setStrategyType(e.target.value)} className="input w-full">
              <option value="grid">网格策略</option>
              <option value="dca">DCA 定投</option>
              <option value="triangular">三角套利</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-muted block mb-1">初始资金 (USDT)</label>
            <input type="number" value={capital} onChange={(e) => setCapital(parseFloat(e.target.value))} className="input w-full" />
          </div>
          <div className="flex items-end gap-2">
            <button onClick={handleDownload} disabled={downloading} className="btn btn-secondary btn-sm w-full">
              {downloading ? '下载中...' : '下载数据'}
            </button>
          </div>
          <div className="flex items-end gap-2">
            <button onClick={handleRunBacktest} disabled={running} className="btn btn-primary btn-sm w-full">
              {running ? '回测中...' : '运行回测'}
            </button>
          </div>
        </div>
      </div>

      {/* K 线图表 */}
      <div>
        {loading ? (
          <div className="panel" style={{ height: 400 }}>
            <Skeleton lines={1} lineHeight={400} width={100} />
          </div>
        ) : klines.length > 0 ? (
          <KlineChart klines={klines} symbol={symbol} height={400} />
        ) : (
          <div className="panel" style={{ height: 200 }}>
            <EmptyState icon="📈" title="暂无 K 线数据" desc="请先下载历史数据" />
          </div>
        )}
      </div>

      {/* 回测结果 */}
      {result && (
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">回测结果 — {result.strategy_name}</span>
          </div>
          <div className="p-3.5 grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: '初始资金', value: formatUsdt(result.initial_capital) },
              { label: '最终资金', value: formatUsdt(result.final_capital), color: result.total_pnl >= 0 ? 'text-up' : 'text-down' },
              { label: '总收益率', value: `${result.total_return_pct}%`, color: result.total_return_pct >= 0 ? 'text-up' : 'text-down' },
              { label: '总交易数', value: result.total_trades },
              { label: '盈利次数', value: result.winning_trades, color: 'text-up' },
              { label: '亏损次数', value: result.losing_trades, color: 'text-down' },
              { label: '胜率', value: `${(result.win_rate * 100).toFixed(1)}%` },
              { label: '最大回撤', value: `${result.max_drawdown_pct}%`, color: 'text-down' },
              { label: '夏普比率', value: result.sharpe_ratio.toFixed(2) },
              { label: '总盈亏', value: formatUsdt(result.total_pnl), color: result.total_pnl >= 0 ? 'text-up' : 'text-down' },
            ].map((item) => (
              <div key={item.label} className="kpi-card">
                <div className="kpi-label">{item.label}</div>
                <div className={`kpi-value ${item.color || ''}`} style={{ fontSize: 18 }}>
                  {item.value}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
