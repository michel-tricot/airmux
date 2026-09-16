import type { InferenceKeyOut, PolicyCreate, PolicyOut, TaxonomyOut } from '@workspace/api-client-react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { PolicyEditor } from '@/pages/app/workspace/PolicyEditor';

const now = '2026-01-01T00:00:00Z';
const catalog: TaxonomyOut = { providers: [], models: [] };
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

function policy(action: PolicyOut['definition']['rules'][number]['action']): PolicyOut {
  return {
    id: '01990aa3-4b4c-7000-8000-000000000001',
    org_id: 'org',
    workspace_id: 'workspace',
    name: 'Production safeguards',
    enabled: true,
    priority: 0,
    definition: { target: { kind: 'workspace' }, rules: [{ match: { kind: 'all_requests' }, action }] },
    created_at: now,
    updated_at: now,
    deleted_at: null,
  };
}

function renderEditor({
  currentPolicy = null,
  onSubmit = async () => {},
  onOpenChange = () => {},
}: {
  currentPolicy?: PolicyOut | null;
  onSubmit?: (payload: PolicyCreate) => Promise<unknown>;
  onOpenChange?: (open: boolean) => void;
} = {}) {
  return render(
    <PolicyEditor
      policy={currentPolicy}
      open
      onOpenChange={onOpenChange}
      onSubmit={onSubmit}
      pending={false}
      users={[{ user_id: '01990aa3-4b4c-7000-8000-000000000003', email: 'service@example.com', name: 'CI', service_account: true }]}
      keys={[inferenceKey]}
      catalog={catalog}
    />,
  );
}

it('selects workspace, users including service accounts, and individual keys explicitly', async () => {
  const user = userEvent.setup();
  renderEditor();
  const appliesTo = screen.getByRole('combobox', { name: 'Applies to' });
  expect(appliesTo).toHaveTextContent('Workspace');
  await user.click(appliesTo);
  await user.click(screen.getByRole('option', { name: 'Selected users' }));
  await user.click(screen.getByRole('button', { name: 'Selected users' }));
  await user.click(screen.getByRole('menuitemcheckbox', { name: /CI.*service account/ }));
  await user.keyboard('{Escape}');
  expect(screen.getByRole('button', { name: 'Selected users' })).toHaveTextContent('Selected users (1)');
  await user.click(appliesTo);
  await user.click(screen.getByRole('option', { name: 'Selected keys' }));
  await user.click(screen.getByRole('button', { name: 'Selected keys' }));
  await user.click(screen.getByRole('menuitemcheckbox', { name: 'Production app' }));
  await user.keyboard('{Escape}');
  expect(screen.getByRole('button', { name: 'Selected keys' })).toHaveTextContent('Selected keys (1)');
});

it('adds an inline rule and saves it only with the policy', async () => {
  const user = userEvent.setup();
  let submitted: PolicyCreate | undefined;
  renderEditor({
    onSubmit: async (payload) => {
      submitted = payload;
    },
  });
  await user.type(screen.getByLabelText('Policy name'), 'Production safeguards');
  await user.click(screen.getByRole('button', { name: 'Add rule' }));
  await user.click(screen.getByRole('button', { name: 'Parameter support' }));
  await user.click(screen.getByRole('button', { name: 'Add rule' }));
  expect(screen.getByText('Require parameter support')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Save policy' }));
  await waitFor(() => expect(submitted?.definition.rules).toEqual([{ match: { kind: 'all_requests' }, action: { kind: 'strict_parameters' } }]));
});

it('discards locally added rules when the policy editor is canceled', async () => {
  const user = userEvent.setup();
  const onSubmit = vi.fn();
  const onOpenChange = vi.fn();
  renderEditor({ onSubmit, onOpenChange });
  await user.click(screen.getByRole('button', { name: 'Add rule' }));
  await user.click(screen.getByRole('button', { name: 'Parameter support' }));
  await user.click(screen.getByRole('button', { name: 'Add rule' }));
  await user.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(onSubmit).not.toHaveBeenCalled();
  expect(onOpenChange).toHaveBeenCalledWith(false);
});

it('edits an inline rule without mutating the original policy value', async () => {
  const user = userEvent.setup();
  const original = policy({ kind: 'request_limits', max_output_tokens: 500 });
  let submitted: PolicyCreate | undefined;
  renderEditor({
    currentPolicy: original,
    onSubmit: async (payload) => {
      submitted = payload;
    },
  });
  await user.click(screen.getByRole('button', { name: 'Edit rule 1' }));
  const limit = screen.getByLabelText('Maximum requested output tokens');
  await user.clear(limit);
  await user.type(limit, '1000');
  await user.click(screen.getByRole('button', { name: 'Update rule' }));
  await user.click(screen.getByRole('button', { name: 'Save policy' }));
  await waitFor(() => expect(submitted?.definition.rules[0].action).toEqual({ kind: 'request_limits', max_output_tokens: 1000 }));
  expect(original.definition.rules[0].action).toEqual({ kind: 'request_limits', max_output_tokens: 500 });
});

it('prevents adding a second fallback rule', async () => {
  const user = userEvent.setup();
  renderEditor({
    currentPolicy: policy({ kind: 'fallback', models: ['backup'], on: ['timeout'], max_attempts: 2, timeout_ms: 1000 }),
  });
  await user.click(screen.getByRole('button', { name: 'Add rule' }));
  expect(screen.getByRole('button', { name: 'Model fallbacks' })).toBeDisabled();
});
