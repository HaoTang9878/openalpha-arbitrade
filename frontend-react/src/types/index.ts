/**
 * 全局类型定义
 *
 * 定义套利系统前后端共享的数据模型，
 * 包括价格快照、套利机会、交易结果、风控状态、系统配置等。
 */

/** 风险等级枚举 */
export type RiskLevel = 'low' | 'medium' | 'high';

/** 订单状态枚举 */
export type OrderStatus =
  | 'pending'
  | 'open'
  | 'partially_filled'
  | 'filled'
  | 'cancelled'
  | 'failed';

/** 价格快照（单个交易所单个交易对） */
export interface PriceTicker {
  bid: number;
  ask: number;
  last: number;
  volume: number;
  timestamp: number;
}

/** 价格快照字典 {exchange: {symbol: PriceTicker}} */
export type PriceSnapshot = Record<string, Record<string, PriceTicker>>;

/** 套利机会 */
export interface ArbitrageOpportunity {
  symbol: string;
  buy_exchange: string;
  sell_exchange: string;
  buy_price: number;
  sell_price: number;
  spread_percent: number;
  net_profit_rate: number;
  estimated_profit: number;
  risk_level: RiskLevel;
  timestamp: number;
}

/** 交易结果 */
export interface TradeResult {
  id: string;
  symbol: string;
  buy_exchange: string;
  sell_exchange: string;
  buy_price: number;
  sell_price: number;
  amount: number;
  buy_order_id: string | null;
  sell_order_id: string | null;
  status: OrderStatus;
  profit: number;
  error: string | null;
  paper_trade: boolean;
  timestamp: string;
}

/** 交易所状态 */
export interface ExchangeStatus {
  name: string;
  enabled: boolean;
  connected: boolean;
  error_count: number;
  latency_ms: number;
  mode?: string;
}

/** 风控状态 */
export interface RiskStatus {
  halted: boolean;
  halt_reason: string;
  open_positions: number;
  max_open_positions: number;
  daily_pnl: number;
  max_daily_loss: number;
  daily_trade_count: number;
  max_daily_trades: number;
  exchange_exposure: Record<string, number>;
  max_exposure_per_exchange: number;
}

/** 系统状态 */
export interface SystemStatus {
  scanner_running: boolean;
  arbitrage_running: boolean;
  exchanges_count: number;
  symbols_count: number;
  opportunities_count: number;
  trades_count: number;
  uptime_seconds: number;
  paper_trade: boolean;
  api_key_status: Record<string, boolean>;
  risk_status: RiskStatus | null;
  timestamp: string;
}

/** 系统配置 */
export interface SystemConfig {
  exchanges: string[];
  symbols: string[];
  min_profitability: number;
  order_amount: number;
  scan_interval: number;
  max_order_age: number;
  paper_trade: boolean;
  fee_rate: number;
  exchange_fees: Record<string, number>;
  top_n_opportunities: number;
  api_key_status?: Record<string, boolean>;
}

/** 每日报告 */
export interface DailyReport {
  date: string;
  total_opportunities: number;
  unique_symbols: number;
  unique_exchange_pairs: number;
  total_trades: number;
  total_profit: number;
  win_rate: number;
  spread_distribution: Record<string, number>;
  top_opportunities: Array<{
    symbol: string;
    buy_exchange: string;
    sell_exchange: string;
    buy_price: number;
    sell_price: number;
    spread_percent: number;
    net_profit_rate: number;
    risk_level: string;
  }>;
  exchange_pair_frequency: Record<string, number>;
  symbol_frequency: Record<string, number>;
}

/** 机会统计 */
export interface OpportunityStats {
  total: number;
  by_risk: Record<string, number>;
  by_symbol: Record<string, number>;
  by_exchange_pair: Record<string, number>;
  spread_distribution: Record<string, number>;
  avg_net_profit_rate: number;
  max_net_profit_rate: number;
}

/** 热力图单元格 */
export interface HeatmapCell {
  symbol: string;
  buy_exchange: string;
  sell_exchange: string;
  spread_percent: number;
  buy_price: number;
  sell_price: number;
  net_profit_rate: number;
}

/** 热力图数据 */
export interface HeatmapData {
  symbols: string[];
  exchange_pairs: string[];
  cells: HeatmapCell[];
}

/** 币种信息 */
export interface SymbolInfo {
  symbol: string;
  base: string;
  category: string;
}

/** 币种列表响应 */
export interface SymbolsResponse {
  symbols: string[];
  symbol_info: SymbolInfo[];
  categories: Record<string, string[]>;
  count: number;
}

/** WebSocket 消息 */
export interface WSMessage {
  type: 'status' | 'prices' | 'opportunities' | 'trade' | 'logs';
  data: unknown;
  timestamp: number;
}

/** 日志条目 */
export interface LogEntry {
  level: string;
  message: string;
  timestamp: number;
}

/** 网格仓位（资金档位） */
export interface Tranche {
  id: string;
  entry_price: number;
  notional_usd: number;
  usdt_amount: number;
  opened_at: string;
  grid_index: number | null;
  buy_exchange: string;
  sell_exchange: string;
  symbol: string;
}

/** 投资组合（账户余额与持仓汇总） */
export interface Portfolio {
  usd_available: number;
  usdt_available: number;
  realized_profit_usd: number;
  open_tranches: Tranche[];
}

/** 系统事件流条目 */
export interface Event {
  ts: string;
  type: string;
  payload: Record<string, unknown>;
}

/** 币种分类标签颜色映射 */
export const CATEGORY_COLORS: Record<string, string> = {
  main: 'bg-accent/15 text-accent',
  defi: 'bg-info/15 text-info',
  layer2: 'bg-up/15 text-up',
  ai: 'bg-purple-500/15 text-purple-400',
  rwa: 'bg-warning/15 text-warning',
  chain: 'bg-down/15 text-down',
  meme: 'bg-pink-500/15 text-pink-400',
  ecosystem: 'bg-teal-500/15 text-teal-400',
  platform: 'bg-indigo-500/15 text-indigo-400',
  other: 'bg-gray-500/15 text-gray-400',
};
