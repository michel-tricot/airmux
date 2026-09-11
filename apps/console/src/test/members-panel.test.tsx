import { useState } from 'react';
import userEvent from '@testing-library/user-event';
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

it('edits an existing member role and displays the saved role', async () => {
  function Roster() {
    const [role, setRole] = useState('member');
    return (
      <MembersPanel
        heading="Members"
        members={[{ user_id: 'user-1', name: 'Alice', role }]}
        emptyText="No members"
        editRole={{
          roles: [
            { value: 'member', label: 'Member' },
            { value: 'admin', label: 'Admin' },
          ],
          pending: false,
          onSave: async (_member, nextRole) => {
            setRole(nextRole);
          },
        }}
      />
    );
  }
  render(<Roster />);
  const user = userEvent.setup();
  await user.click(screen.getByRole('combobox', { name: 'Role for Alice' }));
  await user.click(screen.getByRole('option', { name: 'Admin' }));
  await user.click(screen.getByRole('button', { name: 'Confirm role change' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByRole('combobox', { name: 'Role for Alice' })).toHaveTextContent('Admin');
});
