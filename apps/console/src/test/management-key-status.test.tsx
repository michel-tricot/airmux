import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { KeysTable } from '@/components/shared/keys-table';

describe('management-key status', () => {
  it('shows an expired key as expired', () => {
    render(
      <KeysTable
        resource="management keys"
        keys={[
          {
            id: 'key-1',
            label: 'ci',
            prefix: 'sk-cp-abc',
            status: 'expired',
            created_at: new Date(2026, 8, 11, 13, 45).toISOString(),
          },
        ]}
        emptyText="No keys"
        revokeDescription="Revoke key"
        onRevoke={vi.fn()}
        revokePending={false}
      />,
    );

    expect(screen.getByText('EXPIRED')).toBeInTheDocument();
    expect(screen.getByText('Sep 11, 2026 13:45')).toBeInTheDocument();
  });
});
