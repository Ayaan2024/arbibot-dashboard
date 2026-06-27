import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    entries: ['index.html']
  },
  server: {
    port: 5173,
    host: true,
    watch: {
      ignored: [
        '**/arbibot-deploy/**',
        '**/ArbBot_All_In_One/**',
        '**/New folder/**'
      ]
    }
  },
  build: {
    rollupOptions: {
      input: 'index.html'
    }
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/setupTests.ts'
  }
});
