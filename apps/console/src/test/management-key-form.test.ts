import { describe, expect, it } from 'vitest';
import { managementKeyFormSchema } from '@/components/shared/management-key-form';

describe('management-key form validation', () => {
  it('rejects permission names outside the authority catalog', () => {
    expect(managementKeyFormSchema.safeParse({ label: 'deploy', permissions: ['future.permission'], expiry: 'never' }).success).toBe(false);
  });
});

it.each(['7', '30', '90', '365'] as const)('sets expiry %s days after submission', async (expiry) => {
  const { managementKeyPayload } = await import('@/components/shared/management-key-form');
  const now = new Date('2026-09-11T12:00:00Z');
  expect(managementKeyPayload({ label: 'deploy', permissions: ['workspaces.read'], expiry }, now)).toEqual({
    label: 'deploy',
    permissions: ['workspaces.read'],
    expires_at: new Date(now.getTime() + Number(expiry) * 86400000).toISOString(),
  });
});

it('omits the expiry timestamp for a key that never expires', async () => {
  const { managementKeyPayload } = await import('@/components/shared/management-key-form');
  expect(managementKeyPayload({ label: 'deploy', permissions: ['workspaces.read'], expiry: 'never' }).expires_at).toBeUndefined();
});
