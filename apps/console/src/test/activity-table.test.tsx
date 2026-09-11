import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ActivityTable } from '@/components/shared/activity-table';

describe('ActivityTable', () => {
  it('renders the shared activity vocabulary and contextual labels', () => {
    render(
      <ActivityTable
        entries={[
          {
            id: 1,
            table_name: 'management_key',
            record_id: 'key-1',
            action: 'create',
            user_id: 'user-1',
            occurred_at: '2026-08-18T12:00:00Z',
          },
        ]}
        emptyText="No activity."
        recordLabel={(entry) => (entry.record_id === 'key-1' ? 'deploy' : null)}
        renderActor={(entry) => (entry.user_id === 'user-1' ? 'admin@example.com' : entry.user_id)}
      />,
    );

    expect(screen.getByRole('columnheader', { name: 'Action' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Resource' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Actor' })).toBeInTheDocument();
    expect(screen.getByText(/deploy/)).toBeInTheDocument();
    expect(screen.getByText('admin@example.com')).toBeInTheDocument();
  });
});
