import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const apiProxy = {
  target: process.env.GIGAMIND_DEV_API_ORIGIN || 'http://127.0.0.1:8000',
  changeOrigin: true,
};

export default defineConfig({
  plugins: [react()],
  envDir: process.env.GIGAMIND_DEMO_ENV_DIR || undefined,
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 3000,
    proxy: {
      '/api': apiProxy,
      '/mcp': apiProxy,
      '/openapi.json': apiProxy,
      '/health': apiProxy,
    },
  },
});
