/**
 * 顶部导航栏组件
 *
 * 显示系统状态指示、运行时长、WebSocket 连接状态、
 * 模拟/实盘徽章、监控开关、自动套利开关、Token 输入。
 *
 * 响应式：移动端显示汉堡按钮，桌面端显示完整状态。
 */

import { useState, useEffect } from 'react';
import { useStore } from '../../store/useStore';
import { api, getToken, setToken } from '../../api/client';
import { formatUptime } from '../../utils/format';
import { ThemeToggle } from '../common/ThemeToggle';
import { toast } from '../common/Toast';

interface TopBarProps {
  /** 点击汉堡按钮（移动端展开侧边栏） */
  onMenuClick: () => void;
}

export function TopBar({ onMenuClick }: TopBarProps) {
  const { systemStatus, wsConnected } = useStore();
  const [tokenInput, setTokenInput] = useState('');
  const [hasToken, setHasToken] = useState(!!getToken());

  /** 运行时长实时更新 */
  const [uptime, setUptime] = useState(0);
  useEffect(() => {
    if (systemStatus?.uptime_seconds !== undefined) {
      const baseUptime = systemStatus.uptime_seconds;
      const baseTime = Date.now();
      setUptime(baseUptime);
      const timer = setInterval(() => {
        setUptime(baseUptime + Math.floor((Date.now() - baseTime) / 1000));
      }, 1000);
      return () => clearInterval(timer);
    }
  }, [systemStatus?.uptime_seconds]);

  /** 保存 Token */
  const handleSaveToken = () => {
    const token = tokenInput.trim();
    setToken(token);
    setHasToken(!!token);
    setTokenInput('');
    if (token) {
      toast.success('Token 已保存，正在重连...');
      // 重新加载页面以重新连接 WebSocket
      setTimeout(() => window.location.reload(), 500);
    } else {
      toast.info('Token 已清除');
    }
  };

  /** 切换监控 */
  const handleToggleMonitor = async () => {
    try {
      if (systemStatus?.scanner_running) {
        await api.stopScanner();
      } else {
        await api.startScanner();
      }
    } catch (e) {
      console.error('监控操作失败:', e);
    }
  };

  /** 切换自动套利 */
  const handleToggleArbitrage = async () => {
    try {
      if (systemStatus?.arbitrage_running) {
        await api.stopArbitrage();
      } else {
        await api.startArbitrage();
      }
    } catch (e) {
      console.error('自动套利操作失败:', e);
    }
  };

  const scannerRunning = systemStatus?.scanner_running ?? false;
  const arbitrageRunning = systemStatus?.arbitrage_running ?? false;
  const paperTrade = systemStatus?.paper_trade ?? true;

  return (
    <header
      className="flex items-center justify-between h-14 px-4 border-b border-border flex-shrink-0"
      style={{
        backgroundColor: 'color-mix(in srgb, var(--color-bg-panel) 80%, transparent)',
        backdropFilter: 'blur(12px) saturate(140%)',
        WebkitBackdropFilter: 'blur(12px) saturate(140%)',
      }}
    >
      {/* 左侧：汉堡按钮 + 状态指示 */}
      <div className="flex items-center gap-3">
        {/* 移动端汉堡按钮 */}
        <button
          onClick={onMenuClick}
          className="lg:hidden p-1.5 rounded hover:bg-base-hover"
          aria-label="菜单"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>

        {/* 扫描状态 */}
        <div className="flex items-center gap-2">
          <div className={`status-dot ${scannerRunning ? 'status-dot-running' : 'bg-gray-600'}`} />
          <span className="text-xs hidden sm:inline">
            {scannerRunning ? '扫描中' : '已停止'}
          </span>
        </div>

        {/* 运行时长 */}
        <div className="flex items-center gap-1.5 text-xs text-gray-400 hidden md:flex">
          <span>运行</span>
          <span className="font-mono tabular-nums">{formatUptime(uptime || systemStatus?.uptime_seconds || 0)}</span>
        </div>
      </div>

      {/* 右侧：操作按钮 */}
      <div className="flex items-center gap-2 sm:gap-3">
        {/* WebSocket 状态 */}
        <div className="flex items-center gap-1.5 text-xs">
          <div className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-up' : 'bg-down'}`} />
          <span className="hidden sm:inline text-gray-400">{wsConnected ? '已连接' : '断开'}</span>
        </div>

        {/* 模拟/实盘徽章 */}
        <span className={`badge ${paperTrade ? 'bg-info/15 text-info' : 'bg-down/15 text-down'}`}>
          {paperTrade ? '模拟' : '实盘'}
        </span>

        {/* Token 输入（桌面端） */}
        <div className="hidden lg:flex items-center gap-1.5">
          <input
            type="password"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="管理 Token"
            className="input w-32 text-xs"
          />
          <button onClick={handleSaveToken} className="btn btn-secondary btn-sm">
            {hasToken ? '✓' : '保存'}
          </button>
        </div>

        {/* 主题切换 */}
        <ThemeToggle />

        {/* 监控开关 */}
        <button
          onClick={handleToggleMonitor}
          className={`btn btn-sm ${scannerRunning ? 'btn-danger' : 'btn-primary'}`}
        >
          {scannerRunning ? '停止' : '监控'}
        </button>

        {/* 自动套利开关 */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-gray-400 hidden sm:inline">套利</span>
          <button
            onClick={handleToggleArbitrage}
            className={`
              relative w-9 h-5 rounded-full transition-colors
              ${arbitrageRunning ? 'bg-up' : 'bg-base-hover'}
            `}
            aria-label="自动套利开关"
          >
            <span
              className={`
                absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform
                ${arbitrageRunning ? 'translate-x-4' : ''}
              `}
            />
          </button>
        </div>
      </div>
    </header>
  );
}
