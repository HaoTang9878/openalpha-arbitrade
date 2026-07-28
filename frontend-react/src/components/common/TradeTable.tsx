/**
 * 交易历史表格组件
 *
 * 展示交易记录列表，包含时间、交易对、路由、买卖价、数量、利润、状态。
 * 顶部显示统计卡片（总交易/胜率/累计收益）。
 * 支持滚动查看，模拟交易标记 [模拟]。
 */

import { useEffect } from 'react';
import { useStore } from '../../store/useStore';
import { api } from '../../api/client';
import { formatPrice, formatUsdt, formatTime } from '../../utils/format';
import type { TradeResult } from '../../types';

/** 状态徽章颜色 */
function statusBadgeClass(status: string): string {
  switch (status) {
    case 'filled':
      return 'bg-up/15 text-up';
    case 'failed':
      return 'bg-down/15 text-down';
    default:
      return 'bg-warning/15 text-warning';
  }
}

export function TradeTable() {
  const trades = useStore((s) => s.trades);
  const setTrades = useStore((s) => s.setTrades);

  /** 定时拉取交易历史 */
  useEffect(() => {
    const fetchTrades = async () => {
      try {
        const data = await api.getTrades(50);
        setTrades(data.trades || []);
      } catch (e) {
        console.error('获取交易历史失败:', e);
      }
    };
    fetchTrades();
    const timer = setInterval(fetchTrades, 60000);
    return () => clearInterval(timer);
  }, [setTrades]);

  /** 统计 */
  const total = trades.length;
  const filled = trades.filter((t) => t.status === 'filled').length;
  const winRate = total > 0 ? Math.round((filled / total) * 100) : 0;
  const totalProfit = trades.reduce((sum, t) => sum + (t.profit || 0), 0);

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">交易历史</span>
        <span className="text-xs text-gray-400">{total} 笔</span>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-3 gap-2 p-3">
        <div className="text-center p-2 bg-base-panel rounded">
          <div className="text-lg font-bold font-mono">{total}</div>
          <div className="text-[11px] text-gray-400">总交易</div>
        </div>
        <div className="text-center p-2 bg-base-panel rounded">
          <div className="text-lg font-bold font-mono text-up">{winRate}%</div>
          <div className="text-[11px] text-gray-400">胜率</div>
        </div>
        <div className="text-center p-2 bg-base-panel rounded">
          <div className={`text-lg font-bold font-mono ${totalProfit >= 0 ? 'text-up' : 'text-down'}`}>
            {formatUsdt(totalProfit)}
          </div>
          <div className="text-[11px] text-gray-400">累计收益</div>
        </div>
      </div>

      {/* 交易表格 */}
      <div className="max-h-60 overflow-y-auto">
        <table className="data-table">
          <thead className="sticky top-0 bg-base-panel z-5">
            <tr>
              <th>时间</th>
              <th>交易对</th>
              <th>路由</th>
              <th>买价</th>
              <th>卖价</th>
              <th>数量</th>
              <th>净利润</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center py-8 text-gray-400">
                  暂无交易记录
                </td>
              </tr>
            ) : (
              trades.map((t: TradeResult) => (
                <tr key={t.id}>
                  <td>
                    {formatTime(t.timestamp)}
                    {t.paper_trade && (
                      <span className="text-info text-[10px] ml-1">[模拟]</span>
                    )}
                  </td>
                  <td>{t.symbol}</td>
                  <td className="font-ui">
                    {t.buy_exchange} → {t.sell_exchange}
                  </td>
                  <td>{formatPrice(t.buy_price)}</td>
                  <td>{formatPrice(t.sell_price)}</td>
                  <td>{t.amount || 0}</td>
                  <td className={t.profit >= 0 ? 'text-up' : 'text-down'}>
                    {formatUsdt(t.profit)}
                  </td>
                  <td>
                    <span className={`inline-block px-1.5 py-0.5 rounded text-[11px] font-semibold ${statusBadgeClass(t.status)}`}>
                      {t.status}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
