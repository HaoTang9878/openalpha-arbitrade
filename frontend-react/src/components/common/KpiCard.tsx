/**
 * KPI 卡片组件
 *
 * 显示单个关键指标，包含标签、数值和副标题。
 * 支持自定义颜色（涨绿跌红）。
 */

import { type ReactNode } from 'react';

interface KpiCardProps {
  /** 指标标签 */
  label: string;
  /** 指标数值 */
  value: ReactNode;
  /** 副标题 */
  sub?: string;
  /** 数值颜色类名 */
  colorClass?: string;
}

export function KpiCard({ label, value, sub, colorClass = '' }: KpiCardProps) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${colorClass}`}>{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
    </div>
  );
}
