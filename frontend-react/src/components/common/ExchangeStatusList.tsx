/**
 * 交易所状态列表组件
 *
 * 显示所有交易所的连接状态、延迟、错误数和连接模式。
 * 响应式：桌面端列表，移动端紧凑卡片。
 */

import { useStore } from '../../store/useStore';
import { latencyColor } from '../../utils/format';
import type { ExchangeStatus } from '../../types';

export function ExchangeStatusList() {
  const exchanges = useStore((s) => s.exchanges);

  if (exchanges.length === 0) {
    return <div className="text-center py-8 text-gray-400 text-sm">加载中...</div>;
  }

  return (
    <div className="flex flex-col gap-1.5">
      {exchanges.map((ex: ExchangeStatus) => {
        const statusColor = ex.connected
          ? 'bg-up'
          : ex.error_count > 0
            ? 'bg-warning'
            : 'bg-down';

        return (
          <div
            key={ex.name}
            className="flex flex-col gap-1 px-2.5 py-2 rounded-md bg-base-card border border-transparent hover:border-border-light transition-colors"
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold capitalize">{ex.name}</span>
              <div className={`w-2 h-2 rounded-full ${statusColor}`} />
            </div>
            <div className={`text-[10px] font-mono ${latencyColor(ex.latency_ms)}`}>
              {ex.latency_ms > 0 ? `${ex.latency_ms.toFixed(0)} ms` : '-- ms'}
              {ex.error_count > 0 && (
                <span className="text-down ml-1">({ex.error_count}错误)</span>
              )}
              {ex.mode && (
                <span className="text-gray-500 ml-1">{ex.mode}</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
