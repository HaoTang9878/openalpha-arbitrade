/**
 * 风控可视化面板组件
 *
 * 以进度条形式展示 4 项风控指标：
 * - 同时持仓数
 * - 日交易次数
 * - 日亏损
 * - 单所最大敞口
 *
 * 颜色映射：绿（<50%）→ 黄（50-80%）→ 红（>80%）
 * 风控暂停时显示恢复按钮。
 */

import { useState, useEffect } from 'react';
import { useStore } from '../../store/useStore';
import { api } from '../../api/client';
import { formatUsdt } from '../../utils/format';
import type { RiskStatus } from '../../types';

/** 进度条颜色类名 */
function barColor(pct: number): string {
  if (pct > 80) return 'bg-down';
  if (pct > 50) return 'bg-warning';
  return 'bg-up';
}

/** 单条风控进度条 */
function RiskBar({ label, valueText, pct }: { label: string; valueText: string; pct: number }) {
  return (
    <div className="mb-3.5">
      <div className="flex justify-between text-xs mb-1">
        <span className="text-gray-400">{label}</span>
        <span className="font-mono font-semibold">{valueText}</span>
      </div>
      <div className="h-2 bg-base rounded overflow-hidden">
        <div
          className={`h-full rounded transition-all ${barColor(pct)}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
    </div>
  );
}

export function RiskPanel() {
  const riskStatus = useStore((s) => s.riskStatus);
  const systemStatus = useStore((s) => s.systemStatus);
  const [localRisk, setLocalRisk] = useState<RiskStatus | null>(null);

  /** 定时拉取风控状态 */
  useEffect(() => {
    const fetchRisk = async () => {
      try {
        const r = await api.getRiskStatus();
        setLocalRisk(r);
      } catch (e) {
        console.error('加载风控状态失败:', e);
      }
    };
    fetchRisk();
    const timer = setInterval(fetchRisk, 15000);
    return () => clearInterval(timer);
  }, []);

  const risk = localRisk || riskStatus || systemStatus?.risk_status;

  if (!risk) {
    return <div className="text-center py-8 text-gray-400 text-sm">加载中...</div>;
  }

  const posPct = Math.min((risk.open_positions / risk.max_open_positions) * 100, 100);
  const tradePct = Math.min((risk.daily_trade_count / risk.max_daily_trades) * 100, 100);
  const lossUsed = Math.max(0, -risk.daily_pnl);
  const lossPct = Math.min((lossUsed / risk.max_daily_loss) * 100, 100);
  const exposures = Object.values(risk.exchange_exposure || {});
  const maxExp = Math.max(...exposures, 0);
  const expPct = Math.min((maxExp / risk.max_exposure_per_exchange) * 100, 100);

  /** 恢复风控 */
  const handleResume = async () => {
    try {
      await api.resumeRisk();
      const r = await api.getRiskStatus();
      setLocalRisk(r);
    } catch (e) {
      console.error('恢复风控失败:', e);
    }
  };

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">风控状态</span>
        {risk.halted && (
          <button onClick={handleResume} className="btn btn-secondary btn-sm">
            恢复交易
          </button>
        )}
      </div>
      <div className="p-3.5">
        {risk.halted && (
          <div className="mb-3 p-2 rounded bg-down/15 text-down text-xs text-center">
            ⛔ 风控已暂停：{risk.halt_reason}
          </div>
        )}
        <RiskBar
          label="同时持仓"
          valueText={`${risk.open_positions} / ${risk.max_open_positions}`}
          pct={posPct}
        />
        <RiskBar
          label="日交易次数"
          valueText={`${risk.daily_trade_count} / ${risk.max_daily_trades}`}
          pct={tradePct}
        />
        <RiskBar
          label="日亏损"
          valueText={`${formatUsdt(risk.daily_pnl)} / -$${risk.max_daily_loss}`}
          pct={lossPct}
        />
        <RiskBar
          label="单所最大敞口"
          valueText={`$${maxExp.toFixed(2)} / $${risk.max_exposure_per_exchange}`}
          pct={expPct}
        />
      </div>
    </div>
  );
}
