import path from 'path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, 'src'),
    },
    dedupe: ['react', 'react-dom'],
  },
  test: {
    coverage: {
      exclude: ['src/main.tsx', 'src/test/**'],
      include: ['src/**/*.{ts,tsx}'],
      provider: 'v8',
      reporter: ['text', 'json-summary'],
      thresholds: {
        branches: 55,
        functions: 45,
        lines: 60,
        statements: 60,
      },
    },
    environment: 'jsdom',
    execArgv: process.allowedNodeEnvironmentFlags.has('--no-experimental-webstorage') ? ['--no-experimental-webstorage'] : [],
    maxWorkers: 4,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
});
