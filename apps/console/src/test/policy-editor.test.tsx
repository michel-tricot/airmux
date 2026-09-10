import type { InferenceKeyOut, RuleOut } from '@workspace/api-client-react';
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

const inferenceKey: InferenceKeyOut = {
  id: '01990aa3-4b4c-7000-8000-000000000002',
  org_id: 'org',
  workspace_id: 'workspace',
  user_id: 'user',
  revoked: false,
  label: 'Production app',
  prefix: 'llm_prod',
  created_at: now,
  updated_at: now,
  deleted_at: null,
};

it('selects all keys or individual keys from one Applies to control', async () => {
  const user = userEvent.setup();
  render(<PolicyEditor policy={null} open onOpenChange={() => {}} onSubmit={async () => {}} pending={false} keys={[inferenceKey]} rules={[rule]} />);
  const appliesTo = screen.getByRole('button', { name: 'Applies to' });
  expect(appliesTo).toHaveTextContent(/^All keys$/);
  expect(screen.getByText('Includes future inference keys and playground sessions.')).toBeVisible();

  await user.click(appliesTo);
  expect(screen.getByRole('menuitemcheckbox', { name: 'All keys' })).toBeChecked();
  await user.click(screen.getByRole('menuitemcheckbox', { name: 'Production app' }));
  expect(appliesTo).toHaveTextContent('Selected keys (1)');
  expect(screen.getByRole('menuitemcheckbox', { name: 'Production app' })).toBeChecked();
});

it('attaches and removes reusable rules', async () => {
  const user = userEvent.setup();
  render(<PolicyEditor policy={null} open onOpenChange={() => {}} onSubmit={async () => {}} pending={false} keys={[]} rules={[rule]} />);
  await user.click(screen.getByRole('combobox', { name: 'Add rule' }));
  await user.click(screen.getByRole('option', { name: 'Safe credentials' }));
  expect(screen.getByText('Rules')).toBeVisible();
  expect(screen.queryByRole('button', { name: /Move Safe credentials/ })).not.toBeInTheDocument();
  expect(screen.getByText('Credentials: workspace')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Remove Safe credentials' }));
  expect(screen.queryByText('Credentials: workspace')).not.toBeInTheDocument();
});
