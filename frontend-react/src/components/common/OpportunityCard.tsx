/**
 * 套利机会卡片组件
 *
 * 展示单个套利机会的完整信息：交易对、买卖路由、价差、净利润率、
 * 预估收益、风险等级，以及执行按钮。
 */

import { useState } from 'react';
import { api } from '../../api/client';
import { formatPrice, formatPct, formatUsdt, riskColor } from '../../utils/format';
import type { ArbitrageOpportunity } from '../../types';
import { confirm } from './ConfirmDialog';
import { toast } from './Toast';

interface OpportunityCardProps {
  opportunity: ArbitrageOpportunity;
}

export function OpportunityCard({ opportunity: opp }: OpportunityCardProps) {
  const [executing, setExecuting] = useState(false);
  const profitColor = opp.net_profit_rate >= 0 ? 'text-up' : 'text-gray-400';

  /** 手动执行套利 */
  const handleExecute = async () => {
    const confirmed = await confirm(
      `确认执行 ${opp.symbol} 套利？\n${opp.buy_exchange} 买 → ${opp.sell_exchange} 卖`,
      { title: '执行套利', okText: '执行', cancelText: '取消', okType: 'primary' },
    );
    if (!confirmed) return;

    setExecuting(true);
    try {
      await api.executeTrade(opp);
      toast.success('套利执行完成');
    } catch (e) {
      toast.error('执行失败: ' + (e as Error).message);
    } finally {
      setExecuting(false);
    }
  };

  return (
    <div className="bg-base-card rounded-lg p-3 border border-border hover:border-border-light transition-colors">
      {/* 头部：交易对 + 风险灯 */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-bold">{opp.symbol}</span>
        <div
          className={`w-2.5 h-2.5 rounded-full ${riskColor(opp.risk_level)}`}
          title={opp.risk_level}
        />
      </div>

      {/* 路由 */}
      <div className="flex items-center gap-2 text-xs mb-2">
        <div>
          <div className="font-semibold capitalize">{opp.buy_exchange}</div>
          <div className="text-gray-400 font-mono">买 {formatPrice(opp.buy_price)}</div>
        </div>
        <span className="text-gray-500">→</span>
        <div>
          <div className="font-semibold capitalize">{opp.sell_exchange}</div>
          <div className="text-gray-400 font-mono">卖 {formatPrice(opp.sell_price)}</div>
        </div>
      </div>

      {/* 统计 */}
      <div className="flex justify-between text-xs mb-2">
        <div>
          <span className="text-gray-400">价差 </span>
          <span className="font-mono font-semibold">{formatPct(opp.spread_percent)}</span>
        </div>
        <div>
          <span className="text-gray-400">净利率 </span>
          <span className={`font-mono font-semibold ${profitColor}`}>{formatPct(opp.net_profit_rate)}</span>
        </div>
      </div>

      {/* 收益 + 执行按钮 */}
      <div className="flex justify-between items-center text-xs">
        <div>
          <span className="text-gray-400">预估 </span>
          <span className={`font-mono font-semibold ${profitColor}`}>{formatUsdt(opp.estimated_profit)}</span>
        </div>
        <button
          onClick={handleExecute}
          disabled={executing}
          className="btn btn-secondary btn-sm"
        >
          {executing ? '执行中...' : '执行'}
        </button>
      </div>
    </div>
  );
}
