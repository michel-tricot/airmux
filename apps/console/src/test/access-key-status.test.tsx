import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiKeysTable } from '@/components/shared/api-keys-table';

describe('access-key status', () => {
  it('shows an expired key as expired', () => {
    render(
      <ApiKeysTable
        keys={[
          {
            id: 'key-1',
            label: 'ci',
            prefix: 'sk-cp-abc',
            status: 'expired',
            created_at: '2026-01-01T00:00:00Z',
          },
        ]}
        emptyText="No keys"
        revokeDescription="Revoke key"
        onRevoke={vi.fn()}
        revokePending={false}
      />,
    );

    expect(screen.getByText('EXPIRED')).toBeInTheDocument();
  });
});
