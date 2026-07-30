/**
 * Portfolio 页面 — 投资组合
 *
 * 顶部 4 个 KPI 卡片：USD 余额、USDT 余额、已实现利润、开放 Tranche 数
 * 中部 Tranche 列表：每个仓位卡片展示入场价、当前价、浮动盈亏、网格档位
 * 底部 JSONL 事件流：最近 50 条系统事件
 *
 * 数据加载：React Query（useQuery），失败/空状态分别给出 EmptyState。
 */

import { useMemo } from 'react';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { Wallet, RefreshCw, Layers, Activity } from 'lucide-react';
import { api } from '../api/client';
import { KpiCard } from '../components/common/KpiCard';
import { KpiSkeleton, TableSkeleton } from '../components/common/Skeleton';
import { EmptyState } from '../components/common/EmptyState';
import { toast } from '../components/common/Toast';
import { formatUsdt, formatPrice, formatTime } from '../utils/format';
import type { Portfolio as PortfolioType, Tranche, Event, PriceTicker } from '../types';

/** Portfolio 刷新间隔（毫秒） */
const REFRESH_MS = 10_000;
/** 事件流刷新间隔（毫秒） */
const EVENT_REFRESH_MS = 5_000;

/**
 * Tranche 浮动盈亏卡片
 *
 * 根据当前盘口中间价估算未实现盈亏，未取到价格时仅展示持仓基础信息。
 */
function TrancheCard({ tranche, currentPrice }: { tranche: Tranche; currentPrice: number | null }) {
  // 计算浮动盈亏（不含手续费，按当前中间价估算）
  const unrealized = useMemo(() => {
    if (!currentPrice || !tranche.entry_price) return 0;
    return (currentPrice - tranche.entry_price) * (tranche.usdt_amount / tranche.entry_price);
  }, [currentPrice, tranche.entry_price, tranche.usdt_amount]);

  const pnlPct = useMemo(() => {
    if (!currentPrice || !tranche.entry_price) return 0;
    return ((currentPrice - tranche.entry_price) / tranche.entry_price) * 100;
  }, [currentPrice, tranche.entry_price]);

  const pnlColor = unrealized >= 0 ? 'text-up' : 'text-down';
  const pnlSign = unrealized >= 0 ? '+' : '';

  return (
    <div className="panel">
      <div className="p-3.5">
        {/* 头部：交易对 + 网格档位 */}
        <div className="flex items-center justify-between mb-2.5">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold font-mono">{tranche.symbol}</span>
            {tranche.grid_index !== null && tranche.grid_index !== undefined && (
              <span className="badge bg-accent/15 text-accent">
                档位 #{tranche.grid_index}
              </span>
            )}
          </div>
          <span className="text-[11px] text-gray-400 font-mono">
            {tranche.buy_exchange} → {tranche.sell_exchange}
          </span>
        </div>

        {/* 价格行：入场价 / 当前价 / 盈亏 */}
        <div className="grid grid-cols-3 gap-2 mb-2.5">
          <div>
            <div className="text-[10px] text-gray-400 mb-0.5">入场价</div>
            <div className="text-xs font-mono">${formatPrice(tranche.entry_price)}</div>
          </div>
          <div>
            <div className="text-[10px] text-gray-400 mb-0.5">当前价</div>
            <div className={`text-xs font-mono ${currentPrice ? '' : 'text-gray-500'}`}>
              {currentPrice ? `$${formatPrice(currentPrice)}` : '--'}
            </div>
          </div>
          <div>
            <div className="text-[10px] text-gray-400 mb-0.5">浮动盈亏</div>
            <div className={`text-xs font-mono ${currentPrice ? pnlColor : 'text-gray-500'}`}>
              {currentPrice
                ? `${pnlSign}${formatUsdt(unrealized)} (${pnlSign}${pnlPct.toFixed(2)}%)`
                : '--'}
            </div>
          </div>
        </div>

        {/* 持仓信息 */}
        <div className="flex items-center justify-between text-[11px] pt-2 border-t border-border/40">
          <span className="text-gray-400">名义价值 {formatUsdt(tranche.notional_usd)}</span>
          <span className="text-gray-400 font-mono">
            {tranche.usdt_amount.toFixed(4)} USDT
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * 单条事件行（JSONL 风格）
 */
function EventRow({ event }: { event: Event }) {
  return (
    <div className="flex gap-2 py-1.5 border-b border-border/20 text-[11px] font-mono">
      <span className="text-gray-500 flex-shrink-0">{formatTime(event.ts)}</span>
      <span className="text-accent flex-shrink-0 w-32 truncate">[{event.type}]</span>
      <span className="text-gray-300 truncate flex-1">
        {JSON.stringify(event.payload)}
      </span>
    </div>
  );
}

export function Portfolio() {
  const queryClient = useQueryClient();

  // 拉取投资组合（每 10s 自动刷新）
  const portfolioQuery = useQuery({
    queryKey: ['portfolio'],
    queryFn: api.getPortfolio,
    refetchInterval: REFRESH_MS,
  });

  // 拉取事件流（每 5s 刷新）
  const eventsQuery = useQuery({
    queryKey: ['events', 50],
    queryFn: () => api.getEvents(50),
    refetchInterval: EVENT_REFRESH_MS,
  });

  // 当前价格（用于估算浮动盈亏，失败时静默忽略）
  const pricesQuery = useQuery({
    queryKey: ['prices'],
    queryFn: api.getPrices,
    refetchInterval: REFRESH_MS,
  });

  /** 构建 symbol → 当前中间价 映射，便于 Tranche 卡片查表 */
  const priceMap = useMemo<Record<string, number>>(() => {
    const map: Record<string, number> = {};
    const prices = pricesQuery.data?.prices;
    if (!prices) return map;
    // 取各交易所中间价的平均，缺失数据时跳过
    const symbols = new Set<string>();
    Object.values(prices).forEach((symMap) => {
      Object.keys(symMap).forEach((s) => symbols.add(s));
    });
    symbols.forEach((sym) => {
      const mids: number[] = [];
      Object.values(prices).forEach((symMap) => {
        const t: PriceTicker | undefined = symMap[sym];
        if (t && t.last) mids.push(t.last);
      });
      if (mids.length > 0) {
        map[sym] = mids.reduce((a, b) => a + b, 0) / mids.length;
      }
    });
    return map;
  }, [pricesQuery.data]);

  /** 重置组合的写操作 */
  const resetMutation = useMutation({
    mutationFn: api.resetPortfolio,
    onSuccess: (data) => {
      toast.success(data.message || '投资组合已重置');
      queryClient.invalidateQueries({ queryKey: ['portfolio'] });
    },
    onError: (err: Error) => {
      toast.error('重置失败: ' + err.message);
    },
  });

  const portfolio = portfolioQuery.data;
  const events = eventsQuery.data?.events ?? [];
  const tranches = portfolio?.open_tranches ?? [];

  // 加载中骨架
  if (portfolioQuery.isLoading) {
    return (
      <div className="p-4 overflow-y-auto flex flex-col gap-3">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <KpiSkeleton key={i} />
          ))}
        </div>
        <TableSkeleton rows={4} cols={4} />
      </div>
    );
  }

  // 加载失败
  if (portfolioQuery.isError) {
    return (
      <div className="p-4 overflow-y-auto">
        <EmptyState
          icon="⚠️"
          title="加载投资组合失败"
          desc={(portfolioQuery.error as Error)?.message || '请检查后端服务是否运行'}
          action={
            <button
              className="btn btn-primary btn-sm"
              onClick={() => portfolioQuery.refetch()}
            >
              重试
            </button>
          }
        />
      </div>
    );
  }

  // 未取到数据（理论上不会到这里，兜底）
  if (!portfolio) {
    return (
      <div className="p-4 overflow-y-auto">
        <EmptyState icon="📭" title="暂无投资组合数据" />
      </div>
    );
  }

  return (
    <div className="p-4 overflow-y-auto flex flex-col gap-3">
      {/* 顶部标题栏 + 重置按钮 */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold mb-1 flex items-center gap-2">
            <Wallet className="w-5 h-5 text-accent" strokeWidth={1.5} />
            投资组合
          </h2>
          <p className="text-xs text-gray-400">账户余额、持仓与系统事件总览</p>
        </div>
        <button
          className="btn btn-secondary btn-sm flex items-center gap-1.5"
          disabled={resetMutation.isPending}
          onClick={() => {
            if (window.confirm('确认重置投资组合？此操作将清空余额与所有持仓。')) {
              resetMutation.mutate();
            }
          }}
        >
          <RefreshCw
            className={`w-3.5 h-3.5 ${resetMutation.isPending ? 'animate-spin' : ''}`}
            strokeWidth={2}
          />
          重置组合
        </button>
      </div>

      {/* KPI 卡片行 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard
          label="USD 余额"
          value={formatUsdt(portfolio.usd_available)}
          colorClass="text-accent"
          sub="可用现金"
        />
        <KpiCard
          label="USDT 余额"
          value={portfolio.usdt_available.toFixed(4)}
          colorClass="text-info"
          sub="稳定币持仓"
        />
        <KpiCard
          label="已实现利润"
          value={formatUsdt(portfolio.realized_profit_usd)}
          colorClass={portfolio.realized_profit_usd >= 0 ? 'text-up' : 'text-down'}
          sub="累计平仓盈亏"
        />
        <KpiCard
          label="开放 Tranche"
          value={tranches.length}
          colorClass="text-warning"
          sub="当前持仓档位数"
        />
      </div>

      {/* 中部：Tranche 列表 */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title flex items-center gap-2">
            <Layers className="w-4 h-4" strokeWidth={1.5} />
            持仓 Tranche
          </span>
          <span className="text-xs text-gray-400">{tranches.length} 个仓位</span>
        </div>
        <div className="p-3.5">
          {tranches.length === 0 ? (
            <EmptyState
              icon="📊"
              title="当前无持仓"
              desc="网格策略未触发建仓，或全部 Tranche 已平仓"
            />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {tranches.map((t) => (
                <TrancheCard
                  key={t.id}
                  tranche={t}
                  currentPrice={priceMap[t.symbol] ?? null}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 底部：JSONL 事件流 */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title flex items-center gap-2">
            <Activity className="w-4 h-4" strokeWidth={1.5} />
            事件流
          </span>
          <span className="text-xs text-gray-400">最近 {events.length} 条</span>
        </div>
        <div className="p-3.5 max-h-[420px] overflow-y-auto bg-base-base/50">
          {eventsQuery.isError ? (
            <EmptyState
              icon="⚠️"
              title="事件流加载失败"
              desc={(eventsQuery.error as Error)?.message}
            />
          ) : eventsQuery.isLoading ? (
            <TableSkeleton rows={6} cols={3} />
          ) : events.length === 0 ? (
            <EmptyState icon="📜" title="暂无事件" desc="系统运行后将在此显示事件日志" />
          ) : (
            events.map((ev, idx) => <EventRow key={`${ev.ts}-${idx}`} event={ev} />)
          )}
        </div>
      </div>
    </div>
  );
}