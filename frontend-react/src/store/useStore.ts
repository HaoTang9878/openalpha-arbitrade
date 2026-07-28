/**
 * 全局状态管理（Zustand）
 *
 * 集中管理套利系统的实时数据状态，包括：
 * - 系统状态、配置、价格、机会、交易、交易所状态、风控
 * - WebSocket 连接状态
 * - 日志缓冲区
 *
 * 数据来源：
 * - WebSocket 实时推送（prices/opportunities/trade/logs/status）
 * - REST API 兜底轮询
 */

import { create } from 'zustand';
import type {
  SystemStatus,
  SystemConfig,
  PriceSnapshot,
  ArbitrageOpportunity,
  TradeResult,
  ExchangeStatus,
  RiskStatus,
  LogEntry,
} from '../types';

interface AppState {
  // === 实时数据 ===
  systemStatus: SystemStatus | null;
  config: SystemConfig | null;
  prices: PriceSnapshot;
  opportunities: ArbitrageOpportunity[];
  trades: TradeResult[];
  exchanges: ExchangeStatus[];
  riskStatus: RiskStatus | null;
  logs: LogEntry[];

  // === 连接状态 ===
  wsConnected: boolean;

  // === Actions ===
  setSystemStatus: (status: SystemStatus) => void;
  setConfig: (config: SystemConfig) => void;
  setPrices: (prices: PriceSnapshot) => void;
  setOpportunities: (opps: ArbitrageOpportunity[]) => void;
  addTrade: (trade: TradeResult) => void;
  setTrades: (trades: TradeResult[]) => void;
  setExchanges: (exchanges: ExchangeStatus[]) => void;
  setRiskStatus: (risk: RiskStatus) => void;
  addLog: (log: LogEntry) => void;
  setWsConnected: (connected: boolean) => void;
}

/** 最大日志缓冲区大小 */
const MAX_LOGS = 200;

/** 最大交易历史缓存 */
const MAX_TRADES = 100;

export const useStore = create<AppState>((set) => ({
  // === 初始状态 ===
  systemStatus: null,
  config: null,
  prices: {},
  opportunities: [],
  trades: [],
  exchanges: [],
  riskStatus: null,
  logs: [],
  wsConnected: false,

  // === Actions ===
  setSystemStatus: (status) => set({ systemStatus: status }),

  setConfig: (config) => set({ config }),

  setPrices: (prices) => set({ prices }),

  setOpportunities: (opps) => set({ opportunities: opps }),

  addTrade: (trade) =>
    set((state) => ({
      trades: [trade, ...state.trades].slice(0, MAX_TRADES),
    })),

  setTrades: (trades) => set({ trades }),

  setExchanges: (exchanges) => set({ exchanges }),

  setRiskStatus: (risk) => set({ riskStatus: risk }),

  addLog: (log) =>
    set((state) => ({
      logs: [...state.logs, log].slice(-MAX_LOGS),
    })),

  setWsConnected: (connected) => set({ wsConnected: connected }),
}));
