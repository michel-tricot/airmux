import { describe, expect, it } from 'vitest';
import { accessKeyFormSchema } from '@/components/shared/access-key-form';

describe('access-key form validation', () => {
  it('rejects permission names outside the authority catalog', () => {
    expect(accessKeyFormSchema.safeParse({ label: 'deploy', permissions: ['future.permission'] }).success).toBe(false);
  });
});
