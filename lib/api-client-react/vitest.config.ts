import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    coverage: {
      include: ['src/custom-fetch.ts'],
      provider: 'v8',
      reporter: ['text', 'json-summary'],
      thresholds: {
        branches: 50,
        functions: 80,
        lines: 75,
        statements: 70,
      },
    },
  },
});
