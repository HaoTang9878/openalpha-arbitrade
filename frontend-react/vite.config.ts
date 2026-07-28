import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    // 开发时代理 API 和 WebSocket 到后端 8070 端口
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8070',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8070',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
