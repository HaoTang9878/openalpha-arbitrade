/**
 * Reports 页面 — 每日报告
 *
 * 日期选择 + 当日 KPI 卡片 + 价差分布 + Top10 机会 + 频次统计。
 */

import { useState, useEffect } from 'react';
import { api } from '../api/client';
import { formatPct, formatUsdt } from '../utils/format';
import type { DailyReport as DailyReportType } from '../types';

export function Reports() {
  const [report, setReport] = useState<DailyReportType | null>(null);
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));

  /** 加载报告 */
  const loadReport = async (d?: string) => {
    try {
      const r = await api.getDailyReport(d || date);
      setReport(r);
    } catch (e) {
      console.error('加载报告失败:', e);
    }
  };

  useEffect(() => {
    loadReport();
  }, []);

  if (!report) {
    return <div className="p-4 text-center text-gray-400">加载中...</div>;
  }

  const total = report.total_opportunities || 1;

  return (
    <div className="p-4 overflow-y-auto flex flex-col gap-3">
      {/* 工具栏 */}
      <div className="flex items-center gap-2.5 p-3 bg-base-card rounded-lg border border-border">
        <span className="text-sm font-semibold">每日报告</span>
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="input text-xs"
        />
        <button onClick={() => loadReport()} className="btn btn-primary btn-sm">
          查询
        </button>
        <button
          onClick={() => {
            const today = new Date().toISOString().slice(0, 10);
            setDate(today);
            loadReport(today);
          }}
          className="btn btn-secondary btn-sm"
        >
          今天
        </button>
      </div>

      {/* KPI 卡片 */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {[
          { label: '机会总数', value: report.total_opportunities },
          { label: '交易对数', value: report.unique_symbols },
          { label: '交易所对', value: report.unique_exchange_pairs },
          { label: '交易笔数', value: report.total_trades },
          { label: '累计盈亏', value: formatUsdt(report.total_profit), color: report.total_profit >= 0 ? 'text-up' : 'text-down' },
          { label: '胜率', value: `${(report.win_rate * 100).toFixed(1)}%` },
        ].map((kpi) => (
          <div key={kpi.label} className="bg-base-card rounded-lg border border-border p-3 text-center">
            <div className="text-[11px] text-gray-400 mb-1">{kpi.label}</div>
            <div className={`text-xl font-bold font-mono ${kpi.color || ''}`}>{kpi.value}</div>
          </div>
        ))}
      </div>

      {/* 价差分布 */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">价差分布</span>
        </div>
        <div className="p-3.5">
          <table className="data-table">
            <thead>
              <tr>
                <th>区间</th>
                <th>数量</th>
                <th>占比</th>
              </tr>
            </thead>
            <tbody>
              {['<0.1%', '0.1-0.5%', '0.5-1%', '>1%'].map((k) => {
                const c = report.spread_distribution?.[k] || 0;
                return (
                  <tr key={k}>
                    <td>{k}</td>
                    <td>{c}</td>
                    <td>{((c / total) * 100).toFixed(1)}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Top 10 机会 */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">Top 10 最大价差机会</span>
        </div>
        <div className="p-3.5">
          {report.top_opportunities?.length > 0 ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>交易对</th>
                  <th>路由</th>
                  <th>价差</th>
                  <th>净利率</th>
                  <th>风险</th>
                </tr>
              </thead>
              <tbody>
                {report.top_opportunities.slice(0, 10).map((o, i) => (
                  <tr key={i}>
                    <td>{i + 1}</td>
                    <td>{o.symbol}</td>
                    <td className="font-ui">{o.buy_exchange}→{o.sell_exchange}</td>
                    <td>{formatPct(o.spread_percent)}</td>
                    <td>{formatPct(o.net_profit_rate)}</td>
                    <td>{o.risk_level}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="text-center py-6 text-gray-400">无数据</div>
          )}
        </div>
      </div>

      {/* 频次统计 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">交易所对频次 Top 10</span>
          </div>
          <div className="p-3.5">
            {Object.entries(report.exchange_pair_frequency || {})
              .sort((a, b) => b[1] - a[1])
              .slice(0, 10)
              .map(([pair, count]) => (
                <div key={pair} className="flex justify-between py-1 text-xs border-b border-border/30">
                  <span>{pair}</span>
                  <span className="font-mono">{count}</span>
                </div>
              ))}
            {Object.keys(report.exchange_pair_frequency || {}).length === 0 && (
              <div className="text-center py-4 text-gray-400">无数据</div>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">交易对频次 Top 10</span>
          </div>
          <div className="p-3.5">
            {Object.entries(report.symbol_frequency || {})
              .sort((a, b) => b[1] - a[1])
              .slice(0, 10)
              .map(([sym, count]) => (
                <div key={sym} className="flex justify-between py-1 text-xs border-b border-border/30">
                  <span>{sym}</span>
                  <span className="font-mono">{count}</span>
                </div>
              ))}
            {Object.keys(report.symbol_frequency || {}).length === 0 && (
              <div className="text-center py-4 text-gray-400">无数据</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
