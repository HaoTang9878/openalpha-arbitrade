/**
 * API 客户端
 *
 * 封装所有后端 REST API 调用，统一处理鉴权头、错误处理和响应解析。
 * Token 从 localStorage 读取，写操作自动附加 Authorization 头。
 */

import type {
  SystemStatus,
  SystemConfig,
  PriceSnapshot,
  ArbitrageOpportunity,
  TradeResult,
  ExchangeStatus,
  RiskStatus,
  DailyReport,
  OpportunityStats,
  HeatmapData,
  SymbolsResponse,
} from '../types';

/** API 基础地址（同源访问） */
const API_BASE = window.location.origin;

/** Token 存储 key */
const TOKEN_KEY = 'arbitrage_api_token';

/** 获取已保存的 token */
export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || '';
}

/** 保存 token */
export function setToken(token: string): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

/** 生成鉴权请求头（仅当 token 存在时附加） */
function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** 带 token 的 fetch 封装 */
async function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const headers = { ...authHeaders(), ...options.headers };
  return fetch(url, { ...options, headers });
}

/** GET 请求封装 */
async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) throw new Error(`API ${path} 返回 ${resp.status}`);
  return resp.json();
}

/** 写操作封装（POST/PUT/DELETE） */
async function write<T>(
  path: string,
  method: string,
  body?: unknown,
): Promise<T> {
  const resp = await authFetch(`${API_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ error: resp.statusText }));
    throw new Error(err.error || err.detail || `API ${path} 返回 ${resp.status}`);
  }
  return resp.json();
}

/** API 端点定义 */
export const api = {
  /** 系统状态 */
  getStatus: () => get<SystemStatus>('/api/status'),

  /** 系统配置 */
  getConfig: () => get<SystemConfig>('/api/config'),
  updateConfig: (data: Partial<SystemConfig>) =>
    write<{ status: string; config: SystemConfig }>('/api/config', 'PUT', data),

  /** 价格快照 */
  getPrices: () => get<{ prices: PriceSnapshot; timestamp: number }>('/api/prices'),

  /** 套利机会 */
  getOpportunities: () =>
    get<{ opportunities: ArbitrageOpportunity[]; count: number; timestamp: number }>(
      '/api/opportunities',
    ),
  getOpportunityStats: () => get<OpportunityStats>('/api/opportunities/stats'),

  /** 交易历史 */
  getTrades: (limit = 50) =>
    get<{ trades: TradeResult[]; count: number }>(`/api/trades?limit=${limit}`),
  executeTrade: (opp: Partial<ArbitrageOpportunity>) =>
    write<{ status: string; result: TradeResult }>('/api/trades/execute', 'POST', opp),

  /** 交易所状态 */
  getExchanges: () =>
    get<{ exchanges: ExchangeStatus[]; supported: string[] }>('/api/exchanges'),

  /** 余额查询 */
  getBalances: () => get<Record<string, unknown>>('/api/balances'),

  /** 风控 */
  getRiskStatus: () => get<RiskStatus>('/api/risk/status'),
  resumeRisk: () => write<{ status: string; message: string }>('/api/risk/resume', 'POST'),

  /** 扫描器控制 */
  startScanner: () => write<{ status: string }>('/api/scanner/start', 'POST'),
  stopScanner: () => write<{ status: string }>('/api/scanner/stop', 'POST'),

  /** 自动套利控制 */
  startArbitrage: () => write<{ status: string }>('/api/arbitrage/start', 'POST'),
  stopArbitrage: () => write<{ status: string }>('/api/arbitrage/stop', 'POST'),

  /** 每日报告 */
  getDailyReport: (date?: string) =>
    get<DailyReport>(`/api/daily-report${date ? `?date=${date}` : ''}`),

  /** 热力图 */
  getHeatmap: () => get<HeatmapData>('/api/heatmap'),

  /** 币种管理 */
  getSymbols: () => get<SymbolsResponse>('/api/symbols'),
  updateSymbols: (data: { symbols?: string[]; add?: string[]; remove?: string[] }) =>
    write<{ status: string; symbols: string[]; count: number }>('/api/symbols', 'PUT', data),

  /** API Key 管理 */
  saveApiKey: (exchange: string, apiKey: string, secret: string) =>
    write<{ status: string; exchange: string }>('/api/keys', 'POST', {
      exchange,
      apiKey,
      secret,
    }),
  deleteApiKey: (exchange: string) =>
    write<{ status: string; exchange: string }>(`/api/keys/${exchange}`, 'DELETE'),

  /** 回测引擎 */
  getKlines: (exchange: string, symbol: string, timeframe: string, limit = 500) =>
    get<{ klines: Array<{timestamp:number;open:number;high:number;low:number;close:number;volume:number}>; count: number; total_stored: number }>(
      `/api/backtest/klines?exchange=${exchange}&symbol=${symbol}&timeframe=${timeframe}&limit=${limit}`,
    ),
  downloadKlines: (exchange: string, symbol: string, timeframe: string, days: number) =>
    write<{ status: string; downloaded: number }>('/api/backtest/download', 'POST', {
      exchange, symbol, timeframe, days,
    }),
  runBacktest: (
    strategyType: string,
    config: Record<string, unknown>,
    exchange: string,
    symbol: string,
    timeframe: string,
    initialCapital: number,
  ) =>
    write<Record<string, unknown>>('/api/backtest/run', 'POST', {
      strategy_type: strategyType,
      config,
      exchange,
      symbol,
      timeframe,
      initial_capital: initialCapital,
    }),

  /** 策略管理 */
  getStrategies: () => get<Record<string, unknown>>('/api/strategies'),
  createStrategy: (type: string, name: string, config: Record<string, unknown>) =>
    write<{ status: string; name: string; type: string }>('/api/strategies/create', 'POST', {
      type, name, config,
    }),
  startStrategy: (name: string) =>
    write<{ status: string; name: string }>(`/api/strategies/${name}/start`, 'POST'),
  stopStrategy: (name: string) =>
    write<{ status: string; name: string }>(`/api/strategies/${name}/stop`, 'POST'),
  deleteStrategy: (name: string) =>
    write<{ status: string; name: string }>(`/api/strategies/${name}`, 'DELETE'),

  /** AI 推荐 */
  getAIRecommend: (capital: number, riskTolerance: string) =>
    get<Record<string, unknown>>(`/api/ai/recommend?capital=${capital}&risk_tolerance=${riskTolerance}`),

  /** 用户认证 */
  register: (email: string, password: string) =>
    write<{ status?: string; user_id?: string; email?: string; error?: string }>('/api/auth/register', 'POST', { email, password }),
  login: (email: string, password: string) =>
    write<{ status?: string; access_token?: string; refresh_token?: string; user?: Record<string, unknown>; error?: string }>('/api/auth/login', 'POST', { email, password }),
};

/** WebSocket 连接 URL 构造 */
export function getWsUrl(): string {
  const token = getToken();
  const wsBase = API_BASE.replace('http', 'ws');
  return token ? `${wsBase}/ws?token=${encodeURIComponent(token)}` : `${wsBase}/ws`;
}
