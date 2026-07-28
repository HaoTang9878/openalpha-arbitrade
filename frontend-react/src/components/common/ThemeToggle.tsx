/**
 * 主题切换按钮组件
 *
 * 暗/亮主题一键切换，显示太阳/月亮图标。
 * 使用 useTheme Hook 管理主题状态。
 *
 * 使用方法：
 *   <ThemeToggle />
 */

import { useTheme } from '../../hooks/useTheme';

export function ThemeToggle() {
  const { isDark, toggleTheme } = useTheme();

  return (
    <button
      onClick={toggleTheme}
      className="p-1.5 rounded-lg transition-all hover:bg-base-hover"
      style={{ color: 'var(--color-text-secondary)' }}
      title={isDark ? '切换到亮色主题' : '切换到暗色主题'}
      aria-label="切换主题"
    >
      {isDark ? (
        /* 太阳图标（亮色模式） */
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="5" strokeWidth={2} />
          <path strokeLinecap="round" strokeWidth={2} d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
        </svg>
      ) : (
        /* 月亮图标（暗色模式） */
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
        </svg>
      )}
    </button>
  );
}
