import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
  server: {
    port: 5173,
    open: '/admin/login',
    proxy: {
      // 后端 IngressMiddleware 要求管理/运行入口分别携带入口标识，
      // 开发代理必须代为写入，否则在 allow_loopback_direct=false（默认）时全部 403
      '/api/admin': {
        target: 'http://127.0.0.1:8100',
        changeOrigin: true,
        headers: {
          'X-ToolHive-Ingress': 'admin',
          'X-ToolHive-Client-IP': '127.0.0.1',
        },
      },
      '/api/runtime': {
        target: 'http://127.0.0.1:8100',
        changeOrigin: true,
        headers: {
          'X-ToolHive-Ingress': 'runtime',
          'X-ToolHive-Client-IP': '127.0.0.1',
        },
      },
    },
  },
});
