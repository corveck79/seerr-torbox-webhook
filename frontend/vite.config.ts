import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  base: '/app/',
  build: {
    outDir: '../static/app',
    emptyOutDir: true,
    assetsDir: 'assets',
  },
  server: {
    port: 5173,
    proxy: {
      '/ui/api': 'http://localhost:8088',
      '/login': 'http://localhost:8088',
      '/logout': 'http://localhost:8088',
      '/stream': 'http://localhost:8088',
    },
  },
});
