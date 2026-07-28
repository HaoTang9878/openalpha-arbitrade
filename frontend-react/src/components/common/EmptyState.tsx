/**
 * 空状态组件
 *
 * 数据为空时显示的占位视图，包含 SVG 插画、提示文案和可选操作按钮。
 * 替代简陋的纯文字提示，提升用户体验。
 *
 * 使用方法：
 *   {opps.length === 0 ? (
 *     <EmptyState icon="🔍" title="暂无套利机会" desc="可尝试降低最小利润率阈值" />
 *   ) : (
 *     <OpportunityList opps={opps} />
 *   )}
 */

import { type ReactNode } from 'react';

interface EmptyStateProps {
  /** 图标（emoji 或 SVG） */
  icon?: string;
  /** 标题 */
  title: string;
  /** 描述文案 */
  desc?: string;
  /** 操作按钮 */
  action?: ReactNode;
}

export function EmptyState({
  icon = '📭',
  title,
  desc,
  action,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-6 text-center">
      {/* 插画图标 */}
      <div
        className="text-5xl mb-4 opacity-60"
        style={{ filter: 'grayscale(0.3)' }}
      >
        {icon}
      </div>
      {/* 标题 */}
      <h3
        className="text-base font-semibold mb-1.5"
        style={{ color: 'var(--color-text-secondary)' }}
      >
        {title}
      </h3>
      {/* 描述 */}
      {desc && (
        <p
          className="text-xs max-w-xs"
          style={{ color: 'var(--color-text-muted)' }}
        >
          {desc}
        </p>
      )}
      {/* 操作按钮 */}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
