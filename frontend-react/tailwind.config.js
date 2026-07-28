/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // 背景色（CSS 变量驱动，支持暗/亮双主题）
        base: {
          DEFAULT: 'var(--color-bg-base)',
          panel: 'var(--color-bg-panel)',
          card: 'var(--color-bg-card)',
          elevated: 'var(--color-bg-elevated)',
          hover: 'var(--color-bg-hover)',
        },
        // 数据强调色
        up: 'var(--color-up)',
        down: 'var(--color-down)',
        warning: 'var(--color-warning)',
        info: 'var(--color-info)',
        accent: {
          DEFAULT: 'var(--color-accent)',
          gradient: 'var(--color-accent-gradient)',
        },
        // 文字色
        text: {
          primary: 'var(--color-text-primary)',
          secondary: 'var(--color-text-secondary)',
          muted: 'var(--color-text-muted)',
          disabled: 'var(--color-text-disabled)',
        },
        // 边框色
        border: {
          DEFAULT: 'var(--color-border)',
          light: 'var(--color-border-light)',
          hover: 'var(--color-border-hover)',
        },
      },
      fontFamily: {
        ui: ['IBM Plex Sans', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['IBM Plex Mono', 'JetBrains Mono', 'SF Mono', 'Consolas', 'monospace'],
        display: ['IBM Plex Sans', 'sans-serif'],
      },
      fontSize: {
        xs: ['11px', '16px'],
        sm: ['13px', '20px'],
        base: ['14px', '22px'],
        lg: ['16px', '24px'],
        xl: ['20px', '28px'],
        '2xl': ['26px', '34px'],
        '3xl': ['32px', '40px'],
      },
      borderRadius: {
        sm: '8px',
        md: '12px',
        lg: '16px',
        xl: '20px',
      },
      boxShadow: {
        sm: 'var(--shadow-sm)',
        md: 'var(--shadow-md)',
        lg: 'var(--shadow-lg)',
        'glow-up': 'var(--shadow-glow-up)',
        'glow-down': 'var(--shadow-glow-down)',
      },
      animation: {
        'pulse-slow': 'pulse 2s infinite',
        'flash': 'flash 0.4s ease-out',
        'shimmer': 'shimmer 1.5s infinite linear',
        'slide-in-right': 'slideInRight 0.4s ease-out',
        'pulse-red': 'pulseRed 1s infinite ease',
        'count-up': 'countUp 0.3s ease',
        'fade-in': 'fadeIn 0.3s ease',
        'slide-up': 'slideUp 0.3s ease',
      },
      keyframes: {
        flash: {
          '0%': { backgroundColor: 'rgba(14,203,129,0.2)' },
          '100%': { backgroundColor: 'transparent' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        slideInRight: {
          '0%': { opacity: '0', transform: 'translateX(20px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        pulseRed: {
          '0%, 100%': { borderColor: 'rgba(246,70,93,0.3)' },
          '50%': { borderColor: 'rgba(246,70,93,1)' },
        },
        countUp: {
          '0%': { opacity: '0', transform: 'translateY(5px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
