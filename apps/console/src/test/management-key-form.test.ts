import { describe, expect, it } from 'vitest';
import { managementKeyFormSchema } from '@/components/shared/management-key-form';

describe('management-key form validation', () => {
  it('rejects permission names outside the authority catalog', () => {
    expect(managementKeyFormSchema.safeParse({ label: 'deploy', permissions: ['future.permission'] }).success).toBe(false);
  });
});
