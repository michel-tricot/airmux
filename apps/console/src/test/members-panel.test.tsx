import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MembersPanel } from '@/components/shared/members-panel';

describe('MembersPanel', () => {
  it('supports resource-specific columns without rebuilding the member table', () => {
    render(
      <MembersPanel
        heading="Organization Members"
        members={[{ user_id: 'service-1', name: 'Deploy Bot', email: 'bot@example.com', role: 'admin', service_account: true }]}
        emptyText="No members."
        extraColumns={[
          {
            key: 'kind',
            header: 'Kind',
            cell: (member) => (member.service_account ? 'SERVICE' : 'HUMAN'),
          },
        ]}
      />,
    );

    expect(screen.getByRole('columnheader', { name: 'User' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Kind' })).toBeInTheDocument();
    expect(screen.getByText('Deploy Bot')).toBeInTheDocument();
    expect(screen.getByText('SERVICE')).toBeInTheDocument();
  });
});
