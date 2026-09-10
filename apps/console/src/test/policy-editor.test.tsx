import type { RuleOut } from '@workspace/api-client-react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { PolicyEditor } from '@/pages/app/workspace/PolicyEditor';

const now = '2026-01-01T00:00:00Z';
const rule: RuleOut = {
  id: '01990aa3-4b4c-7000-8000-000000000001',
  org_id: 'org',
  workspace_id: 'workspace',
  name: 'Safe credentials',
  definition: { match: { kind: 'all_requests' }, action: { kind: 'credential_access', scopes: ['workspace'] } },
  created_at: now,
  updated_at: now,
  deleted_at: null,
};

it('keeps the key target label short and explains its scope outside the dropdown', () => {
  render(<PolicyEditor policy={null} open onOpenChange={() => {}} onSubmit={async () => {}} pending={false} keys={[]} rules={[rule]} />);
  expect(screen.getByRole('combobox', { name: 'Applies to' })).toHaveTextContent(/^All keys$/);
  expect(screen.getByText('Includes future inference keys and playground sessions.')).toBeVisible();
});

it('attaches and removes reusable rules', async () => {
  const user = userEvent.setup();
  render(<PolicyEditor policy={null} open onOpenChange={() => {}} onSubmit={async () => {}} pending={false} keys={[]} rules={[rule]} />);
  await user.click(screen.getByRole('combobox', { name: 'Add rule' }));
  await user.click(screen.getByRole('option', { name: 'Safe credentials' }));
  expect(screen.getByText('Credentials: workspace')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Remove Safe credentials' }));
  expect(screen.queryByText('Credentials: workspace')).not.toBeInTheDocument();
});
