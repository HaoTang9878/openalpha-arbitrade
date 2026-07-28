/**
 * App 根组件
 *
 * 组合路由、布局（Sidebar + TopBar）和 WebSocket 连接。
 * 使用 React Router 6 管理 7 个页面路由。
 */

import { useState } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Sidebar } from './components/layout/Sidebar';
import { TopBar } from './components/layout/TopBar';
import { ToastContainer } from './components/common/Toast';
import { ConfirmDialog } from './components/common/ConfirmDialog';
import { useWebSocket } from './hooks/useWebSocket';
import { useTheme } from './hooks/useTheme';
import { Dashboard } from './pages/Dashboard';
import { Bots } from './pages/Bots';
import { Backtest } from './pages/Backtest';
import { Heatmap } from './pages/Heatmap';
import { Reports } from './pages/Reports';
import { Settings } from './pages/Settings';

function AppContent() {
  /** 移动端侧边栏开关 */
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  /** 建立 WebSocket 连接 */
  useWebSocket();

  /** 初始化主题（暗色/亮色） */
  useTheme();

  return (
    <div className="flex h-screen overflow-hidden bg-base text-gray-100">
      {/* 侧边栏 */}
      <Sidebar
        mobileOpen={mobileSidebarOpen}
        onClose={() => setMobileSidebarOpen(false)}
      />

      {/* 主内容区 */}
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar onMenuClick={() => setMobileSidebarOpen(true)} />

        {/* 路由页面 */}
        <main className="flex-1 overflow-hidden">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/bots" element={<Bots />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/heatmap" element={<Heatmap />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>

      {/* 全局 Toast 通知 */}
      <ToastContainer />
      {/* 全局确认对话框 */}
      <ConfirmDialog />
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
}

export default App;
