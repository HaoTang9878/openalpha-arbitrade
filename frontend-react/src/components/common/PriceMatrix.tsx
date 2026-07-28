/**
 * 价格对比矩阵组件
 *
 * 行=交易对，列=交易所，单元格显示 bid/ask 价格。
 * 高亮最优买价（最低 ask）和最优卖价（最高 bid）。
 * 支持搜索筛选和分类筛选。
 */

import { useState, useMemo } from 'react';
import { useStore } from '../../store/useStore';
import { formatPrice, formatPct } from '../../utils/format';
import type { PriceTicker } from '../../types';

/** 币种分类映射 */
const SYMBOL_CATEGORIES: Record<string, string[]> = {
  main: ['BTC', 'ETH', 'SOL', 'BNB', 'XRP'],
  defi: ['DOGE', 'AVAX', 'ARB', 'OP', 'LINK', 'UNI', 'AAVE', 'MKR', 'CRV', 'SNX'],
  layer2: ['MATIC', 'STRK', 'BLUR'],
  ai: ['FET', 'AGIX', 'RNDR', 'TAO'],
  rwa: ['ONDO', 'PENDLE'],
  chain: ['SUI', 'SEI', 'TIA', 'INJ', 'APT', 'NEAR', 'ATOM', 'DOT'],
  meme: ['PEPE', 'WIF', 'BONK', 'FLOKI', 'SHIB'],
  ecosystem: ['LDO', 'ENA'],
  platform: ['GT', 'CRO'],
};

/** 获取币种分类 */
function getSymbolCategory(symbol: string): string {
  const base = symbol.split('/')[0];
  for (const [cat, symbols] of Object.entries(SYMBOL_CATEGORIES)) {
    if (symbols.includes(base)) return cat;
  }
  return 'other';
}

export function PriceMatrix() {
  const prices = useStore((s) => s.prices);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');

  /** 获取所有交易所和交易对 */
  const { exchanges, symbols } = useMemo(() => {
    const exList = Object.keys(prices).sort();
    const symSet = new Set<string>();
    exList.forEach((ex) => Object.keys(prices[ex]).forEach((s) => symSet.add(s)));
    return { exchanges: exList, symbols: Array.from(symSet).sort() };
  }, [prices]);

  /** 筛选后的交易对 */
  const filteredSymbols = useMemo(() => {
    return symbols.filter((sym) => {
      // 分类筛选
      if (filter !== 'all' && getSymbolCategory(sym) !== filter) return false;
      // 搜索筛选
      if (search.trim() && !sym.toLowerCase().includes(search.trim().toLowerCase())) {
        return false;
      }
      return true;
    });
  }, [symbols, filter, search]);

  if (exchanges.length === 0) {
    return <div className="text-center py-8 text-gray-400 text-sm">等待数据...</div>;
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">价格对比矩阵</span>
      </div>

      {/* 筛选栏 */}
      <div className="flex gap-2 px-3.5 py-2 items-center border-b border-border">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索币种（如 BTC、PEPE）..."
          className="input flex-1 text-xs"
        />
        <div className="flex gap-1">
          {['all', 'main', 'defi', 'chain', 'meme'].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2 py-0.5 rounded text-[11px] border ${
                filter === f
                  ? 'bg-accent text-black border-accent'
                  : 'bg-base border-border text-gray-400'
              }`}
            >
              {f === 'all' ? '全部' : f === 'main' ? '主流' : f === 'defi' ? 'DeFi' : f === 'chain' ? '公链' : 'Meme'}
            </button>
          ))}
        </div>
      </div>

      {/* 表格 */}
      <div className="overflow-x-auto max-h-80 overflow-y-auto">
        <table className="data-table">
          <thead className="sticky top-0 bg-base-panel z-10">
            <tr>
              <th>交易对</th>
              {exchanges.map((ex) => (
                <th key={ex}>{ex.charAt(0).toUpperCase() + ex.slice(1)}</th>
              ))}
              <th>最大价差</th>
            </tr>
          </thead>
          <tbody>
            {filteredSymbols.map((sym) => {
              // 找出最优买价和卖价
              let bestAsk = Infinity;
              let bestAskEx = '';
              let bestBid = 0;
              let bestBidEx = '';
              const exData: Record<string, PriceTicker> = {};

              exchanges.forEach((ex) => {
                const ticker = prices[ex]?.[sym];
                if (ticker && ticker.ask > 0 && ticker.bid > 0) {
                  exData[ex] = ticker;
                  if (ticker.ask < bestAsk) {
                    bestAsk = ticker.ask;
                    bestAskEx = ex;
                  }
                  if (ticker.bid > bestBid) {
                    bestBid = ticker.bid;
                    bestBidEx = ex;
                  }
                }
              });

              const maxSpread = bestBid > 0 && bestAsk < Infinity
                ? (bestBid - bestAsk) / bestAsk
                : 0;

              return (
                <tr key={sym}>
                  <td className="font-semibold">{sym}</td>
                  {exchanges.map((ex) => {
                    const t = exData[ex];
                    if (!t) return <td key={ex} className="text-gray-500">--</td>;
                    const isBest = ex === bestAskEx || ex === bestBidEx;
                    return (
                      <td key={ex} className={isBest ? 'font-bold' : ''}>
                        <div className="text-up leading-tight">{formatPrice(t.bid)}</div>
                        <div className="text-down leading-tight">{formatPrice(t.ask)}</div>
                      </td>
                    );
                  })}
                  <td>
                    <span
                      className={`inline-block px-2 py-0.5 rounded text-xs font-mono font-semibold ${
                        maxSpread >= 0.003 ? 'bg-up/15 text-up' : 'bg-gray-500/15 text-gray-400'
                      }`}
                    >
                      {formatPct(maxSpread)}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
