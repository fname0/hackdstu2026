import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// Ключ карты 2ГИС берём из корневого .env (DGIS_API_KEY). Ключ карты по своей природе клиентский.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', '');
  return {
    plugins: [react()],
    define: { 'import.meta.env.VITE_DGIS_KEY': JSON.stringify(env.DGIS_API_KEY ?? '') },
    server: {
      port: 5173,
      proxy: { '/api': process.env.API_URL ?? 'http://localhost:8000' },
      fs: { allow: ['..'] },
      watch: process.env.VITE_POLLING ? { usePolling: true, interval: 300 } : undefined,
    },
  };
});
