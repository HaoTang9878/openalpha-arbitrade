/**
 * 数字滚动动画组件
 *
 * 数字变化时执行 count-up 滚动动画，提升 KPI 数值的视觉反馈。
 * 使用 requestAnimationFrame 实现平滑过渡。
 *
 * 使用方法：
 *   <AnimatedNumber value={totalProfit} format="usdt" />
 *   <AnimatedNumber value={oppCount} format="int" />
 */

import { useEffect, useRef, useState } from 'react';

interface AnimatedNumberProps {
  /** 目标数值 */
  value: number;
  /** 格式化类型 */
  format?: 'int' | 'usdt' | 'pct' | 'price';
  /** 动画时长（ms），默认 500 */
  duration?: number;
  /** 小数位数（price 类型按量级自适应，此参数仅对 int/usdt 生效） */
  decimals?: number;
  /** 颜色类名 */
  className?: string;
}

/** 缓动函数（ease-out） */
function easeOut(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

/** 格式化数值 */
function formatValue(val: number, format: string, decimals?: number): string {
  switch (format) {
    case 'usdt': {
      const sign = val >= 0 ? '' : '-';
      return sign + '$' + Math.abs(val).toFixed(decimals ?? 2);
    }
    case 'pct':
      return (val * 100).toFixed(3) + '%';
    case 'price':
      if (val >= 1000) return val.toFixed(2);
      if (val >= 1) return val.toFixed(4);
      return val.toFixed(6);
    case 'int':
    default:
      return Math.round(val).toString();
  }
}

export function AnimatedNumber({
  value,
  format = 'int',
  duration = 500,
  decimals,
  className = '',
}: AnimatedNumberProps) {
  const [displayValue, setDisplayValue] = useState(value);
  const fromRef = useRef(value);
  const rafRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    const from = fromRef.current;
    const to = value;
    const start = performance.now();

    // 值未变化则跳过动画
    if (from === to) {
      setDisplayValue(to);
      return;
    }

    const animate = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = easeOut(progress);
      const current = from + (to - from) * eased;
      setDisplayValue(current);

      if (progress < 1) {
        rafRef.current = requestAnimationFrame(animate);
      } else {
        fromRef.current = to;
        setDisplayValue(to);
      }
    };

    rafRef.current = requestAnimationFrame(animate);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [value, duration]);

  return (
    <span className={`font-mono tabular-nums animate-count-up ${className}`}>
      {formatValue(displayValue, format, decimals)}
    </span>
  );
}
