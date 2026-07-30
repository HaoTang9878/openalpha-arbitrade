/**
 * Dashboard 页面 — 实时监控
 *
 * 三栏布局（桌面端）/ 单栏堆叠（移动端）：
 * - 左栏：交易所状态 + 风控面板
 * - 中栏：KPI 卡片 + 价格矩阵 + 交易历史
 * - 右栏：套利机会实时流
 */

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useStore } from '../store/useStore';
import { api } from '../api/client';
import { KpiCard } from '../components/common/KpiCard';
import { ExchangeStatusList } from '../components/common/ExchangeStatusList';
import { PriceMatrix } from '../components/common/PriceMatrix';
import { OpportunityCard } from '../components/common/OpportunityCard';
import { RiskPanel } from '../components/common/RiskPanel';
import { TradeTable } from '../components/common/TradeTable';
import { formatUsdt } from '../utils/format';
import type { Portfolio } from '../types';

export function Dashboard() {
  const { systemStatus, opportunities, setSystemStatus, setExchanges } = useStore();

  /** 定时拉取系统状态和交易所状态 */
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const [status, exData] = await Promise.all([api.getStatus(), api.getExchanges()]);
        setSystemStatus(status);
        setExchanges(exData.exchanges || []);
      } catch (e) {
        console.error('获取状态失败:', e);
      }
    };
    fetchStatus();
    const timer = setInterval(fetchStatus, 10000);
    return () => clearInterval(timer);
  }, [setSystemStatus, setExchanges]);

  /** 每 10 秒刷新一次投资组合数据（余额、利润、开放 Tranche） */
  const { data: portfolio } = useQuery<Portfolio>({
    queryKey: ['portfolio'],
    queryFn: () => api.getPortfolio(),
    refetchInterval: 10000,
  });

  const oppCount = opportunities.length;
  const tradeCount = systemStatus?.trades_count ?? 0;
  const totalProfit = useStore((s) =>
    s.trades.reduce((sum, t) => sum + (t.profit || 0), 0),
  );

  return (
    <div className="flex flex-col lg:flex-row gap-3 p-3 h-full overflow-hidden">
      {/* 左栏：交易所状态 + 风控（桌面端侧边栏，移动端折叠到顶部） */}
      <aside className="w-full lg:w-60 flex-shrink-0 flex flex-col gap-3 lg:overflow-y-auto">
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">交易所状态</span>
          </div>
          <div className="p-2.5">
            <ExchangeStatusList />
          </div>
        </div>
        <RiskPanel />
      </aside>

      {/* 中栏：KPI + 价格矩阵 + 交易历史 */}
      <main className="flex-1 min-w-0 overflow-y-auto flex flex-col gap-3">
        {/* KPI 卡片行 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KpiCard
            label="套利机会"
            value={oppCount}
            sub={`${systemStatus?.exchanges_count ?? 0} 所 · ${systemStatus?.symbols_count ?? 0} 币`}
            colorClass="text-up"
          />
          <KpiCard
            label="今日交易"
            value={tradeCount}
            sub="笔成交"
            colorClass="text-info"
          />
          <KpiCard
            label="累计收益"
            value={formatUsdt(totalProfit)}
            sub="含模拟交易"
            colorClass={totalProfit >= 0 ? 'text-up' : 'text-down'}
          />
          <KpiCard
            label="监控交易对"
            value={systemStatus?.symbols_count ?? 0}
            sub={`${systemStatus?.exchanges_count ?? 0} 个交易所`}
          />
          {portfolio && (
            <>
              <KpiCard
                label="USD 余额"
                value={formatUsdt(portfolio.usd_available)}
              />
              <KpiCard
                label="USDT 余额"
                value={formatUsdt(portfolio.usdt_available)}
              />
              <KpiCard
                label="已实现利润"
                value={formatUsdt(portfolio.realized_profit_usd)}
                colorClass={portfolio.realized_profit_usd >= 0 ? 'text-up' : 'text-down'}
              />
              <KpiCard
                label="开放 Tranche"
                value={portfolio.open_tranches.length}
              />
            </>
          )}
        </div>

        <PriceMatrix />
        <TradeTable />
      </main>

      {/* 右栏：套利机会流 */}
      <aside className="w-full lg:w-72 flex-shrink-0 lg:overflow-y-auto">
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">套利机会</span>
            <span className="text-xs text-gray-400">{oppCount} 个</span>
          </div>
          <div className="p-2.5 flex flex-col gap-2 max-h-[calc(100vh-200px)] overflow-y-auto">
            {oppCount === 0 ? (
              <div className="text-center py-10 text-gray-400 text-sm">
                暂无套利机会
                <br />
                <span className="text-xs">可尝试降低最小利润率阈值</span>
              </div>
            ) : (
              opportunities.map((opp, i) => (
                <OpportunityCard key={`${opp.symbol}-${i}`} opportunity={opp} />
              ))
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}
