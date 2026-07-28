/**
 * 格式化工具函数
 *
 * 提供价格、百分比、USDT 金额、时间、运行时长等的格式化，
 * 供所有组件统一调用。
 */

/** 格式化价格（按数量级自适应小数位） */
export function formatPrice(price: number | undefined | null): string {
  if (!price || price <= 0) return '--';
  if (price >= 1000) return price.toFixed(2);
  if (price >= 1) return price.toFixed(4);
  return price.toFixed(6);
}

/** 格式化百分比（输入为小数，输出 % 字符串） */
export function formatPct(val: number | undefined | null): string {
  if (val === null || val === undefined) return '--';
  return (val * 100).toFixed(3) + '%';
}

/** 格式化 USDT 金额 */
export function formatUsdt(val: number | undefined | null): string {
  if (!val) return '$0.00';
  const sign = val >= 0 ? '' : '-';
  return sign + '$' + Math.abs(val).toFixed(4);
}

/** 格式化运行时长（秒 → HH:MM:SS） */
export function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return [h, m, s].map((v) => String(v).padStart(2, '0')).join(':');
}

/** 格式化时间戳 → HH:MM:SS */
export function formatTime(ts: number | string | undefined): string {
  if (!ts) return '--';
  const d = new Date(typeof ts === 'number' ? ts : Date.parse(ts));
  return d.toLocaleTimeString('zh-CN', { hour12: false });
}

/** 价差百分比 → 热力图颜色（绿→黄→红） */
export function heatmapColor(spreadPct: number): string {
  const t = Math.min(Math.max(spreadPct / 1.0, 0), 1);
  if (t < 0.5) {
    const r = Math.round(14 + (251 - 14) * (t / 0.5));
    const g = Math.round(203 + (191 - 203) * (t / 0.5));
    const b = Math.round(129 + (36 - 129) * (t / 0.5));
    return `rgb(${r},${g},${b})`;
  }
  const r = Math.round(251 + (246 - 251) * ((t - 0.5) / 0.5));
  const g = Math.round(191 + (70 - 191) * ((t - 0.5) / 0.5));
  const b = Math.round(36 + (93 - 36) * ((t - 0.5) / 0.5));
  return `rgb(${r},${g},${b})`;
}

/** 风险等级 → 颜色类名 */
export function riskColor(level: string): string {
  switch (level) {
    case 'low':
      return 'bg-up';
    case 'medium':
      return 'bg-warning';
    case 'high':
      return 'bg-down';
    default:
      return 'bg-gray-500';
  }
}

/** 延迟 → 颜色类名 */
export function latencyColor(ms: number): string {
  if (ms < 300) return 'text-up';
  if (ms < 800) return 'text-warning';
  return 'text-down';
}
