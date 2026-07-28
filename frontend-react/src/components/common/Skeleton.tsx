/**
 * 骨架屏组件
 *
 * 数据加载时显示的占位动画，使用 shimmer 光波扫描效果。
 * 替代白屏等待，提升感知速度。
 *
 * 使用方法：
 *   {loading ? <Skeleton lines={3} /> : <DataView data={data} />}
 */

interface SkeletonProps {
  /** 行数 */
  lines?: number;
  /** 高度（px），默认 14 */
  lineHeight?: number;
  /** 宽度百分比，默认 100 */
  width?: number;
  /** 圆角 */
  rounded?: 'sm' | 'md' | 'full';
  className?: string;
}

/** 单行骨架 */
export function Skeleton({
  lines = 1,
  lineHeight = 14,
  width = 100,
  rounded = 'sm',
  className = '',
}: SkeletonProps) {
  const radius = rounded === 'full' ? '9999px' : rounded === 'md' ? '12px' : '8px';
  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="skeleton"
          style={{
            height: `${lineHeight}px`,
            width: `${i === lines - 1 && lines > 1 ? width * 0.7 : width}%`,
            borderRadius: radius,
          }}
        />
      ))}
    </div>
  );
}

/** KPI 卡片骨架 */
export function KpiSkeleton() {
  return (
    <div className="kpi-card">
      <Skeleton lines={1} lineHeight={12} width={40} />
      <div className="mt-2">
        <Skeleton lines={1} lineHeight={28} width={70} />
      </div>
      <div className="mt-1.5">
        <Skeleton lines={1} lineHeight={11} width={50} />
      </div>
    </div>
  );
}

/** 表格行骨架 */
export function TableSkeleton({ rows = 5, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="flex flex-col gap-1">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-3">
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} lineHeight={16} width={100 / cols - 2} />
          ))}
        </div>
      ))}
    </div>
  );
}
