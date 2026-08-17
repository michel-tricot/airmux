import path from 'path';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

import runtimeErrorOverlay from '@replit/vite-plugin-runtime-error-modal';

const rawPort = process.env.PORT ?? '5000';

const port = Number(rawPort);

if (Number.isNaN(port) || port <= 0) {
  throw new Error(`Invalid PORT value: "${rawPort}"`);
}

const basePath = process.env.BASE_PATH ?? '/';

const controlPlaneUrl = process.env.CONTROL_PLANE_URL ?? 'http://127.0.0.1:8000';
const dataPlaneUrl = process.env.DATA_PLANE_URL ?? 'http://127.0.0.1:8080';
// Replit's preview proxies through a dynamic *.replit.dev host, so host
// filtering must be disabled in this environment; ALLOWED_HOSTS can still
// pin an explicit list elsewhere.
const allowedHosts: string[] | true = process.env.ALLOWED_HOSTS
  ? process.env.ALLOWED_HOSTS.split(',')
      .map((host) => host.trim())
      .filter(Boolean)
  : true;

export default defineConfig({
  base: basePath,
  plugins: [
    react(),
    tailwindcss(),
    runtimeErrorOverlay(),
    ...(process.env.NODE_ENV !== 'production' && process.env.REPL_ID !== undefined
      ? [
          await import('@replit/vite-plugin-cartographer').then((m) =>
            m.cartographer({
              root: path.resolve(import.meta.dirname, '..'),
            }),
          ),
          await import('@replit/vite-plugin-dev-banner').then((m) => m.devBanner()),
        ]
      : []),
  ],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, 'src'),
    },
    dedupe: ['react', 'react-dom'],
  },
  root: path.resolve(import.meta.dirname),
  build: {
    outDir: path.resolve(import.meta.dirname, 'dist/public'),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/@radix-ui/')) return 'radix';
          if (id.includes('/@tanstack/') || id.includes('/react/') || id.includes('/react-dom/') || id.includes('/wouter/')) return 'framework';
        },
      },
    },
  },
  server: {
    port,
    strictPort: true,
    host: '0.0.0.0',
    allowedHosts,
    fs: {
      strict: true,
    },
    proxy: {
      '/api': { target: controlPlaneUrl, changeOrigin: false },
      '/inf': { target: dataPlaneUrl, changeOrigin: true },
    },
  },
  preview: {
    port,
    host: '0.0.0.0',
    allowedHosts,
  },
});
