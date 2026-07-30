/**
 * KPI 卡片组件
 *
 * 显示单个关键指标，包含标签、数值、副标题和趋势指示。
 * 支持自定义颜色（涨绿跌红）和趋势箭头。
 */

import { type ReactNode } from 'react';
import { ArrowUp, ArrowDown, Minus } from 'lucide-react';

interface KpiCardProps {
  /** 指标标签 */
  label: string;
  /** 指标数值 */
  value: ReactNode;
  /** 副标题 */
  sub?: string;
  /** 数值颜色类名 */
  colorClass?: string;
  /** 趋势方向：up/down/flat，不传则不显示趋势 */
  trend?: 'up' | 'down' | 'flat';
  /** 趋势数值（如 +2.5% 或 -1.2） */
  trendValue?: string;
}

export function KpiCard({ label, value, sub, colorClass = '', trend, trendValue }: KpiCardProps) {
  const trendIcon = trend === 'up' ? ArrowUp : trend === 'down' ? ArrowDown : Minus;
  const trendColor = trend === 'up' ? 'text-up' : trend === 'down' ? 'text-down' : 'text-gray-400';
  const TrendIcon = trendIcon;

  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${colorClass}`}>{value}</div>
      {trend && (
        <div className={`flex items-center gap-0.5 text-xs mt-0.5 ${trendColor}`}>
          <TrendIcon className="w-3 h-3" strokeWidth={2} />
          {trendValue && <span className="font-mono">{trendValue}</span>}
        </div>
      )}
      {sub && !trend && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
    </div>
  );
}
