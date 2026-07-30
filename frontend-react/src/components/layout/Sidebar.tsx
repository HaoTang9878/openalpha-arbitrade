/**
 * 侧边栏导航组件
 *
 * 桌面端：固定左侧边栏，显示导航菜单
 * 移动端：抽屉式侧边栏，点击汉堡按钮展开/收起
 *
 * 导航项：监控、策略机器人、回测、热力图、报告、设置
 */

import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Bot,
  TrendingUp,
  Flame,
  FileText,
  Wallet,
  Settings,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

interface SidebarProps {
  /** 移动端是否展开 */
  mobileOpen: boolean;
  /** 关闭移动端抽屉 */
  onClose: () => void;
}

/** 导航菜单项定义 */
const NAV_ITEMS: { path: string; label: string; icon: LucideIcon }[] = [
  { path: '/', label: '实时监控', icon: LayoutDashboard },
  { path: '/bots', label: '策略机器人', icon: Bot },
  { path: '/backtest', label: '回测', icon: TrendingUp },
  { path: '/heatmap', label: '价差热力图', icon: Flame },
  { path: '/reports', label: '每日报告', icon: FileText },
  { path: '/portfolio', label: '投资组合', icon: Wallet },
  { path: '/settings', label: '设置', icon: Settings },
];

export function Sidebar({ mobileOpen, onClose }: SidebarProps) {
  return (
    <>
      {/* 移动端遮罩层 */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={onClose}
        />
      )}

      {/* 侧边栏主体 */}
      <aside
        className={`
          fixed lg:sticky top-0 left-0 z-50
          w-60 h-screen
          border-r border-border
          flex flex-col
          transition-transform duration-300
          ${mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        `}
        style={{
          backgroundColor: 'color-mix(in srgb, var(--color-bg-panel) 80%, transparent)',
          backdropFilter: 'blur(12px) saturate(140%)',
          WebkitBackdropFilter: 'blur(12px) saturate(140%)',
        }}
      >
        {/* Logo 区域 */}
        <div className="flex items-center gap-2 px-5 h-14 border-b border-border">
          <span className="text-lg font-bold text-accent">OpenAlpha</span>
          <span className="text-xs text-gray-400">套利系统</span>
        </div>

        {/* 导航菜单 */}
        <nav className="flex-1 overflow-y-auto p-3">
          <div className="text-xs uppercase tracking-wide text-gray-500 px-2 mb-2">
            导航
          </div>
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === '/'}
                onClick={onClose}
                className={({ isActive }) => `
                  flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium
                  transition-colors mb-1
                  ${isActive
                    ? 'bg-accent/10 text-accent border border-accent/30'
                    : 'text-gray-400 hover:text-gray-100 hover:bg-base-hover border border-transparent'
                  }
                `}
              >
                <Icon className="w-4 h-4 flex-shrink-0" strokeWidth={1.5} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        {/* 底部版本信息 */}
        <div className="p-3 border-t border-border text-xs text-gray-500">
          <div>OpenAlpha Arbitrage v2.0</div>
          <div className="mt-1">React + TypeScript + Vite</div>
        </div>
      </aside>
    </>
  );
}
