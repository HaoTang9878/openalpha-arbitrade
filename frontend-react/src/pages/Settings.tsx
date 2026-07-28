/**
 * Settings 页面 — 系统设置
 *
 * 包含：策略配置面板、币种管理、API Key 管理。
 * 响应式：桌面端双栏，移动端单栏堆叠。
 */

import { useState, useEffect } from 'react';
import { api } from '../api/client';
import { useStore } from '../store/useStore';
import { CATEGORY_COLORS } from '../types';
import type { SymbolsResponse } from '../types';

export function Settings() {
  const { config, setConfig } = useStore();
  const [symbols, setSymbols] = useState<SymbolsResponse | null>(null);
  const [newSymbol, setNewSymbol] = useState('');
  const [apiKeyStatus, setApiKeyStatus] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);

  /** 加载配置和币种 */
  useEffect(() => {
    const load = async () => {
      try {
        const [cfg, symData, status] = await Promise.all([
          api.getConfig(),
          api.getSymbols(),
          api.getStatus(),
        ]);
        setConfig(cfg);
        setSymbols(symData);
        setApiKeyStatus(status.api_key_status || {});
      } catch (e) {
        console.error('加载设置失败:', e);
      }
    };
    load();
  }, [setConfig]);

  /** 保存配置 */
  const handleSaveConfig = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await api.updateConfig(config);
      alert('配置已保存');
    } catch (e) {
      alert('保存失败: ' + (e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  /** 添加币种 */
  const handleAddSymbol = async () => {
    const sym = newSymbol.trim().toUpperCase();
    if (!sym) return;
    try {
      await api.updateSymbols({ add: [sym] });
      setNewSymbol('');
      const data = await api.getSymbols();
      setSymbols(data);
    } catch (e) {
      alert('添加失败: ' + (e as Error).message);
    }
  };

  /** 删除币种 */
  const handleRemoveSymbol = async (symbol: string) => {
    if (!confirm(`确认删除 ${symbol}？`)) return;
    try {
      await api.updateSymbols({ remove: [symbol] });
      const data = await api.getSymbols();
      setSymbols(data);
    } catch (e) {
      alert('删除失败: ' + (e as Error).message);
    }
  };

  return (
    <div className="p-4 overflow-y-auto grid grid-cols-1 md:grid-cols-2 gap-3">
      {/* 策略配置 */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">策略配置</span>
        </div>
        <div className="p-3.5">
          {config && (
            <>
              <ConfigRow label="最小净利润率">
                <input
                  type="number"
                  step="0.001"
                  min="0.001"
                  value={config.min_profitability}
                  onChange={(e) => setConfig({ ...config, min_profitability: parseFloat(e.target.value) })}
                  className="input w-28"
                />
              </ConfigRow>
              <ConfigRow label="单笔下单量">
                <input
                  type="number"
                  step="0.01"
                  min="0.001"
                  value={config.order_amount}
                  onChange={(e) => setConfig({ ...config, order_amount: parseFloat(e.target.value) })}
                  className="input w-28"
                />
              </ConfigRow>
              <ConfigRow label="扫描间隔（秒）">
                <select
                  value={config.scan_interval}
                  onChange={(e) => setConfig({ ...config, scan_interval: parseInt(e.target.value) })}
                  className="input w-28"
                >
                  {[3, 5, 10, 15, 30].map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              </ConfigRow>
              <ConfigRow label="订单超时（秒）">
                <input
                  type="number"
                  value={config.max_order_age}
                  onChange={(e) => setConfig({ ...config, max_order_age: parseInt(e.target.value) })}
                  className="input w-28"
                />
              </ConfigRow>
              <ConfigRow label="手续费率">
                <input
                  type="number"
                  step="0.0001"
                  min="0"
                  max="0.01"
                  value={config.fee_rate}
                  onChange={(e) => setConfig({ ...config, fee_rate: parseFloat(e.target.value) })}
                  className="input w-28"
                />
              </ConfigRow>
              <ConfigRow label="最大机会数">
                <select
                  value={config.top_n_opportunities}
                  onChange={(e) => setConfig({ ...config, top_n_opportunities: parseInt(e.target.value) })}
                  className="input w-28"
                >
                  {[10, 20, 30, 50].map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              </ConfigRow>
              <ConfigRow label="模拟交易">
                <button
                  onClick={() => setConfig({ ...config, paper_trade: !config.paper_trade })}
                  className={`relative w-10 h-5.5 rounded-full transition-colors ${config.paper_trade ? 'bg-up' : 'bg-base-hover'}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${config.paper_trade ? 'translate-x-5' : ''}`} />
                </button>
              </ConfigRow>
              <button
                onClick={handleSaveConfig}
                disabled={saving}
                className="btn btn-primary btn-sm w-full mt-3"
              >
                {saving ? '保存中...' : '保存配置'}
              </button>
            </>
          )}
        </div>
      </div>

      {/* 币种管理 */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">币种管理</span>
          <span className="text-xs text-gray-400">{symbols?.count || 0} 个</span>
        </div>
        <div className="p-2.5 max-h-80 overflow-y-auto">
          {symbols?.symbol_info.map((info) => (
            <div
              key={info.symbol}
              className="flex items-center justify-between px-2.5 py-1.5 rounded mb-1 bg-base border border-border hover:border-border-light"
            >
              <span className="text-xs font-mono font-semibold">{info.symbol}</span>
              <span className="flex items-center gap-1.5">
                <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase ${CATEGORY_COLORS[info.category] || CATEGORY_COLORS.other}`}>
                  {info.category}
                </span>
                <button
                  onClick={() => handleRemoveSymbol(info.symbol)}
                  className="btn btn-danger btn-sm"
                  style={{ padding: '2px 6px', fontSize: '10px' }}
                >
                  删
                </button>
              </span>
            </div>
          ))}
        </div>
        <div className="flex gap-1.5 p-2.5 border-t border-border">
          <input
            type="text"
            value={newSymbol}
            onChange={(e) => setNewSymbol(e.target.value)}
            placeholder="输入交易对，如 ADA/USDT"
            className="input flex-1 text-xs"
          />
          <button onClick={handleAddSymbol} className="btn btn-primary btn-sm">添加</button>
        </div>
      </div>

      {/* API Key 管理 */}
      <div className="panel md:col-span-2">
        <div className="panel-header">
          <span className="panel-title">API Key 管理</span>
          <span className="text-xs text-gray-400">
            {Object.values(apiKeyStatus).filter(Boolean).length}/{Object.keys(apiKeyStatus).length} 已配置
          </span>
        </div>
        <div className="p-3.5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {Object.entries(apiKeyStatus).map(([ex, configured]) => (
            <ApiKeyItem key={ex} exchange={ex} configured={configured} />
          ))}
        </div>
      </div>
    </div>
  );
}

/** 配置行 */
function ConfigRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <span className="text-xs text-gray-400">{label}</span>
      {children}
    </div>
  );
}

/** API Key 项 */
function ApiKeyItem({ exchange, configured }: { exchange: string; configured: boolean }) {
  const [apiKey, setApiKey] = useState('');
  const [secret, setSecret] = useState('');

  const handleSave = async () => {
    if (!apiKey || !secret) {
      alert('请填写 API Key 和 Secret');
      return;
    }
    try {
      await api.saveApiKey(exchange, apiKey, secret);
      alert(`${exchange} 保存成功`);
      setApiKey('');
      setSecret('');
    } catch (e) {
      alert('保存失败: ' + (e as Error).message);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`确认删除 ${exchange} 的 API Key？`)) return;
    try {
      await api.deleteApiKey(exchange);
    } catch (e) {
      alert('删除失败: ' + (e as Error).message);
    }
  };

  return (
    <div className="border border-border rounded-lg p-2.5 bg-base">
      <div className="flex justify-between items-center mb-1.5">
        <span className="text-xs font-semibold capitalize">{exchange}</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded ${configured ? 'bg-up/15 text-up' : 'bg-down/15 text-down'}`}>
          {configured ? '已配置' : '未配置'}
        </span>
      </div>
      <input
        type="password"
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
        placeholder="API Key"
        className="input w-full text-xs mb-1"
      />
      <input
        type="password"
        value={secret}
        onChange={(e) => setSecret(e.target.value)}
        placeholder="Secret"
        className="input w-full text-xs mb-1.5"
      />
      <div className="flex gap-1">
        <button onClick={handleSave} className="btn btn-primary btn-sm flex-1" style={{ fontSize: '11px' }}>保存</button>
        <button onClick={handleDelete} className="btn btn-danger btn-sm flex-1" style={{ fontSize: '11px' }}>删除</button>
      </div>
    </div>
  );
}
