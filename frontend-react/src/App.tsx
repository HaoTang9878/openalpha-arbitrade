/**
 * App 根组件
 *
 * 路由结构：
 * - /landing: 独立全屏 Landing 展示页（无 Sidebar/TopBar）
 * - 其他路由: 控制台布局（Sidebar + TopBar + WebSocket）
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
import { Portfolio } from './pages/Portfolio';
import { LandingPage } from './pages/LandingPage';

/** 控制台布局：Sidebar + TopBar + 页面内容 */
function ConsoleLayout() {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  useWebSocket();
  useTheme();

  return (
    <div className="flex h-screen overflow-hidden bg-base text-gray-100">
      <Sidebar
        mobileOpen={mobileSidebarOpen}
        onClose={() => setMobileSidebarOpen(false)}
      />
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar onMenuClick={() => setMobileSidebarOpen(true)} />
        <main className="flex-1 overflow-hidden">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/bots" element={<Bots />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/heatmap" element={<Heatmap />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
      <ToastContainer />
      <ConfirmDialog />
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Landing 页面：独立全屏，不包含控制台布局 */}
        <Route path="/landing" element={<LandingPage />} />
        {/* 控制台页面：包含 Sidebar + TopBar */}
        <Route path="/*" element={<ConsoleLayout />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
