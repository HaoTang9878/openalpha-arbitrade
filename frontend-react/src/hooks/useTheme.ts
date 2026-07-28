/**
 * 主题切换 Hook
 *
 * 管理暗色/亮色主题切换，持久化到 localStorage，
 * 默认跟随系统 prefers-color-scheme。
 * 通过设置 document.documentElement.dataset.theme 切换 CSS 变量。
 */

import { useState, useEffect, useCallback } from 'react';

type Theme = 'dark' | 'light';

const THEME_KEY = 'openalpha_theme';

/** 获取系统偏好主题 */
function getSystemTheme(): Theme {
  if (typeof window !== 'undefined' && window.matchMedia) {
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  return 'dark';
}

/** 获取已保存的主题（无保存则跟随系统） */
function getStoredTheme(): Theme {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return getSystemTheme();
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(getStoredTheme);

  /** 应用主题到 DOM */
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  /** 切换主题 */
  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark';
      localStorage.setItem(THEME_KEY, next);
      return next;
    });
  }, []);

  /** 设置指定主题 */
  const setTheme = useCallback((t: Theme) => {
    localStorage.setItem(THEME_KEY, t);
    setThemeState(t);
  }, []);

  return { theme, toggleTheme, setTheme, isDark: theme === 'dark' };
}
