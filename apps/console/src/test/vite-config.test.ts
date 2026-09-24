import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { describe, expect, it } from 'vitest';

function configuredAllowedHosts({ allowedHosts, replId }: { allowedHosts?: string; replId?: string } = {}) {
  const configUrl = pathToFileURL(path.resolve(import.meta.dirname, '../../vite.config.ts')).href;
  const source = `
    const { default: config } = await import(${JSON.stringify(configUrl)});
    process.stdout.write(JSON.stringify({ server: config.server?.allowedHosts, preview: config.preview?.allowedHosts }));
  `;
  const output = execFileSync('bun', ['-e', source], {
    encoding: 'utf8',
    env: { ...process.env, NODE_ENV: 'production', ALLOWED_HOSTS: allowedHosts, REPL_ID: replId },
  });
  return JSON.parse(output) as { server: string[] | true; preview: string[] | true };
}

function configuredTestLimits() {
  const configUrl = pathToFileURL(path.resolve(import.meta.dirname, '../../vitest.config.ts')).href;
  const source = `
    const { default: config } = await import(${JSON.stringify(configUrl)});
    process.stdout.write(JSON.stringify({ maxWorkers: config.test?.maxWorkers ?? null, testTimeout: config.test?.testTimeout ?? null }));
  `;
  return JSON.parse(execFileSync('bun', ['-e', source], { encoding: 'utf8' })) as { maxWorkers: number | string | null; testTimeout: number | null };
}

describe('Vite host allowlist', () => {
  it('uses Vite host validation defaults outside Replit', () => {
    expect(configuredAllowedHosts()).toEqual({
      server: [],
      preview: [],
    });
  });

  it('allows Replit preview hosts', () => {
    expect(configuredAllowedHosts({ replId: 'test' })).toEqual({ server: true, preview: true });
  });

  it('applies an explicit allowlist in every environment', () => {
    expect(configuredAllowedHosts({ allowedHosts: 'console.example.com, api.example.com', replId: 'test' })).toEqual({
      server: ['console.example.com', 'api.example.com'],
      preview: ['console.example.com', 'api.example.com'],
    });
  });
});

it('uses every host worker with contention-safe test deadlines', () => {
  expect(configuredTestLimits()).toEqual({ maxWorkers: '100%', testTimeout: 30_000 });
});
