import { useState } from 'react';
import type { Permission } from '@workspace/api-client-react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { PermissionChecklist } from '@/components/shared/access-key-form';

function Picker() {
  const [permissions, setPermissions] = useState<Permission[]>(['workspaces.read', 'usage.read']);
  return (
    <PermissionChecklist
      value={permissions}
      onChange={setPermissions}
      availablePermissions={['workspaces.read', 'workspaces.update', 'usage.read']}
      grantablePermissions={['workspaces.read', 'workspaces.update']}
      canIssue
    />
  );
}

it('filters by readable labels and exact permission names without losing hidden selections', async () => {
  render(<Picker />);
  const user = userEvent.setup();
  expect(screen.getByText('2 selected')).toBeInTheDocument();
  await user.type(screen.getByRole('textbox', { name: 'Search permissions' }), 'Edit');
  expect(screen.getByRole('checkbox', { name: 'workspaces.update' })).toHaveTextContent('Edit');
  expect(screen.queryByRole('checkbox', { name: 'usage.read' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('checkbox', { name: 'workspaces.update' }));
  expect(screen.getByText('3 selected')).toBeInTheDocument();
  await user.clear(screen.getByRole('textbox', { name: 'Search permissions' }));
  expect(screen.getByRole('checkbox', { name: 'usage.read' })).toBeChecked();
  await user.type(screen.getByRole('textbox', { name: 'Search permissions' }), 'workspaces.read');
  expect(screen.getByRole('checkbox', { name: 'workspaces.read' })).toBeChecked();
});

it('supports keyboard selection and removal without regranting unavailable permissions', async () => {
  render(<Picker />);
  const user = userEvent.setup();
  const usage = screen.getByRole('checkbox', { name: 'usage.read' });
  usage.focus();
  await user.keyboard(' ');
  expect(usage).not.toBeChecked();
  expect(usage).toBeDisabled();
  expect(screen.getByText('1 selected')).toBeInTheDocument();
  await user.type(screen.getByRole('textbox', { name: 'Search permissions' }), 'nothing-matches');
  expect(screen.getByText('No matching permissions')).toBeInTheDocument();
});
