/**
 * Heatmap 页面 — 价差热力图
 *
 * 交易对 × 交易所对矩阵，单元格颜色映射价差大小（绿→黄→红）。
 * 悬浮显示买卖价详情，点击可执行套利。
 */

import { useState, useEffect, useMemo } from 'react';
import { api } from '../api/client';
import { heatmapColor } from '../utils/format';
import type { HeatmapData, HeatmapCell } from '../types';

export function Heatmap() {
  const [data, setData] = useState<HeatmapData | null>(null);
  const [loading, setLoading] = useState(false);

  /** 加载热力图数据 */
  const loadHeatmap = async () => {
    setLoading(true);
    try {
      const d = await api.getHeatmap();
      setData(d);
    } catch (e) {
      console.error('加载热力图失败:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHeatmap();
    const timer = setInterval(loadHeatmap, 10000);
    return () => clearInterval(timer);
  }, []);

  /** 构建查找表 {symbol: {pairKey: cell}} */
  const cellMap = useMemo(() => {
    const map: Record<string, Record<string, HeatmapCell>> = {};
    data?.cells.forEach((c) => {
      const key = `${c.buy_exchange}→${c.sell_exchange}`;
      if (!map[c.symbol]) map[c.symbol] = {};
      map[c.symbol][key] = c;
    });
    return map;
  }, [data]);

  if (!data || data.symbols.length === 0) {
    return (
      <div className="p-4">
        <div className="panel">
          <div className="text-center py-12 text-gray-400">
            {loading ? '加载中...' : '暂无价格数据，点击刷新'}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 h-full overflow-auto">
      {/* 图例 */}
      <div className="flex items-center gap-2 mb-3 text-xs text-gray-400">
        <span>价差小</span>
        <div
          className="w-48 h-3 rounded"
          style={{ background: 'linear-gradient(to right, #0ECB81, #FBBF24, #F6465D)' }}
        />
        <span>价差大</span>
        <span className="ml-auto">点击单元格可执行套利</span>
        <button onClick={loadHeatmap} className="btn btn-secondary btn-sm">
          刷新
        </button>
      </div>

      {/* 热力图表格 */}
      <div className="panel overflow-auto max-h-[calc(100vh-140px)]">
        <table className="border-collapse text-[11px] font-mono">
          <thead>
            <tr>
              <th className="sticky top-0 left-0 z-20 bg-base-panel px-2 py-1.5 border border-border text-gray-400 whitespace-nowrap">
                交易对
              </th>
              {data.exchange_pairs.map((pair) => (
                <th
                  key={pair}
                  className="sticky top-0 z-10 bg-base-panel px-2 py-1.5 border border-border text-gray-400 whitespace-nowrap"
                >
                  {pair}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.symbols.map((sym) => (
              <tr key={sym}>
                <td className="sticky left-0 z-5 bg-base-card px-2 py-1 border border-border font-semibold whitespace-nowrap">
                  {sym}
                </td>
                {data.exchange_pairs.map((pair) => {
                  const cell = cellMap[sym]?.[pair];
                  if (!cell) {
                    return (
                      <td
                        key={pair}
                        className="px-1.5 py-1 border border-border text-center text-gray-600"
                      >
                        --
                      </td>
                    );
                  }
                  const sp = cell.spread_percent * 100;
                  const title = `${sym} ${pair}\n买: ${cell.buy_price}\n卖: ${cell.sell_price}\n价差: ${sp.toFixed(3)}%\n净利率: ${(cell.net_profit_rate * 100).toFixed(3)}%`;
                  return (
                    <td
                      key={pair}
                      className="px-1.5 py-1 border border-border text-center cursor-pointer hover:scale-105 transition-transform"
                      style={{ backgroundColor: heatmapColor(sp) }}
                      title={title}
                      onClick={() => {
                        if (confirm(`执行 ${sym} ${pair} 套利？`)) {
                          api.executeTrade(cell);
                        }
                      }}
                    >
                      {sp.toFixed(2)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
