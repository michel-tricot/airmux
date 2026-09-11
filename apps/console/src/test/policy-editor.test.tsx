import type { InferenceKeyOut, PolicyCreate, RuleCreate, RuleOut } from '@workspace/api-client-react';
import { render, screen, waitFor } from '@testing-library/react';
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

const catalog = { providers: [], models: [] };

function fallbackRule(id: string, name: string): RuleOut {
  return {
    ...rule,
    id,
    name,
    definition: {
      match: { kind: 'all_requests' },
      action: { kind: 'fallback', models: ['openai/gpt-test'], on: ['timeout'], max_attempts: 2, timeout_ms: 1000 },
    },
  };
}

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
  await user.click(screen.getByRole('button', { name: 'Add existing rule' }));
  await user.click(screen.getByRole('option', { name: /Safe credentials/ }));
  expect(screen.getByText('Rules')).toBeVisible();
  expect(screen.queryByRole('button', { name: /Move Safe credentials/ })).not.toBeInTheDocument();
  expect(screen.getByText('Credentials: workspace')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Remove Safe credentials' }));
  expect(screen.queryByText('Credentials: workspace')).not.toBeInTheDocument();
});

it('uses policy reordering as the only priority control', () => {
  render(<PolicyEditor policy={null} open onOpenChange={() => {}} onSubmit={async () => {}} pending={false} keys={[]} rules={[rule]} />);

  expect(screen.queryByLabelText(/Priority/)).not.toBeInTheDocument();
});

it('offers at most one fallback rule per policy', async () => {
  const user = userEvent.setup();
  const firstFallback = fallbackRule('01990aa3-4b4c-7000-8000-000000000003', 'Primary fallback');
  const secondFallback = fallbackRule('01990aa3-4b4c-7000-8000-000000000004', 'Secondary fallback');
  render(
    <PolicyEditor
      policy={null}
      open
      onOpenChange={() => {}}
      onSubmit={async () => {}}
      pending={false}
      keys={[]}
      rules={[firstFallback, secondFallback, rule]}
      ruleComposer={{
        catalog,
        usageByRuleId: new Map(),
        createPending: false,
        updatePending: false,
        create: async () => secondFallback,
        update: async (existingRule) => existingRule,
      }}
    />,
  );

  await user.click(screen.getByRole('button', { name: 'Add existing rule' }));
  await user.click(screen.getByRole('option', { name: new RegExp(firstFallback.name) }));
  await user.click(screen.getByRole('button', { name: 'Add existing rule' }));

  expect(screen.queryByRole('option', { name: new RegExp(secondFallback.name) })).not.toBeInTheDocument();
  expect(screen.getByRole('option', { name: new RegExp(rule.name) })).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Close' }));
  await user.click(screen.getByRole('button', { name: 'Create rule' }));

  expect(screen.getByRole('button', { name: 'Model fallbacks' })).toBeDisabled();
});

it('searches existing shared rules before attaching one', async () => {
  const user = userEvent.setup();
  const otherRule = { ...rule, id: '01990aa3-4b4c-7000-8000-000000000005', name: 'Other rule' };
  render(<PolicyEditor policy={null} open onOpenChange={() => {}} onSubmit={async () => {}} pending={false} keys={[]} rules={[rule, otherRule]} />);

  await user.click(screen.getByRole('button', { name: 'Add existing rule' }));
  await user.type(screen.getByRole('combobox', { name: 'Search shared rules' }), 'safe');

  expect(screen.getByRole('option', { name: /Safe credentials/ })).toBeVisible();
  expect(screen.queryByRole('option', { name: /Other rule/ })).not.toBeInTheDocument();
});

it('creates and selects a shared rule without losing the policy draft', async () => {
  const user = userEvent.setup();
  let createdPayload: RuleCreate | undefined;
  let submittedPolicy: PolicyCreate | undefined;
  const createdRule = {
    ...rule,
    id: '01990aa3-4b4c-7000-8000-000000000006',
    name: 'Strict parameters',
    definition: { match: { kind: 'all_requests' }, action: { kind: 'strict_parameters' } },
  } satisfies RuleOut;
  render(
    <PolicyEditor
      policy={null}
      open
      onOpenChange={() => {}}
      onSubmit={async (payload) => {
        submittedPolicy = payload;
      }}
      pending={false}
      keys={[]}
      rules={[]}
      ruleComposer={{
        catalog,
        usageByRuleId: new Map(),
        createPending: false,
        updatePending: false,
        create: async (payload) => {
          createdPayload = payload;
          return createdRule;
        },
        update: async () => createdRule,
      }}
    />,
  );

  await user.type(screen.getByLabelText('Policy name'), 'Production safeguards');
  await user.click(screen.getByRole('button', { name: 'Create rule' }));
  expect(screen.getByRole('heading', { name: 'Choose a rule type' })).toBeVisible();
  expect(screen.getByRole('button', { name: 'Model fallbacks' })).toBeEnabled();
  await user.click(screen.getByRole('button', { name: 'Back to policy' }));
  expect(screen.getByLabelText('Policy name')).toHaveValue('Production safeguards');

  await user.click(screen.getByRole('button', { name: 'Create rule' }));
  await user.click(screen.getByRole('button', { name: 'Parameter support' }));
  expect(screen.getByRole('heading', { name: 'Create and add parameter support rule' })).toBeVisible();
  expect(screen.getByText(/saved to the Rule library/)).toBeVisible();
  await user.type(screen.getByLabelText('Rule name'), 'Strict parameters');
  await user.click(screen.getByRole('button', { name: 'Create and add rule' }));

  await waitFor(() => expect(createdPayload?.definition.action).toEqual({ kind: 'strict_parameters' }));
  expect(screen.getByRole('heading', { name: 'Create policy' })).toBeVisible();
  expect(screen.getByLabelText('Policy name')).toHaveValue('Production safeguards');
  expect(screen.getByText('Strict parameters')).toBeVisible();
  expect(screen.getByText('New')).toBeVisible();

  await user.click(screen.getByRole('button', { name: 'Save policy' }));
  await waitFor(() => expect(submittedPolicy?.definition.rule_ids).toEqual([createdRule.id]));
});

it('shows shared rule usage before editing from a policy', async () => {
  const user = userEvent.setup();
  let updatedPayload: RuleCreate | undefined;
  const updatedRule = { ...rule, name: 'Safer credentials' };
  render(
    <PolicyEditor
      policy={null}
      open
      onOpenChange={() => {}}
      onSubmit={async () => {}}
      pending={false}
      keys={[]}
      rules={[rule]}
      ruleComposer={{
        catalog,
        usageByRuleId: new Map([[rule.id, 2]]),
        createPending: false,
        updatePending: false,
        create: async () => rule,
        update: async (_rule, payload) => {
          updatedPayload = payload;
          return updatedRule;
        },
      }}
    />,
  );

  await user.click(screen.getByRole('button', { name: 'Add existing rule' }));
  await user.click(screen.getByRole('option', { name: /Safe credentials/ }));
  await user.click(screen.getByRole('button', { name: 'Edit Safe credentials' }));

  expect(screen.getByRole('heading', { name: 'Edit credential access rule' })).toBeVisible();
  expect(screen.getByText('Used by 2 policies')).toBeVisible();
  expect(screen.getByText(/updates every policy that uses it/)).toBeVisible();
  await user.clear(screen.getByLabelText('Rule name'));
  await user.type(screen.getByLabelText('Rule name'), updatedRule.name);
  await user.click(screen.getByRole('button', { name: 'Save rule' }));

  await waitFor(() => expect(updatedPayload?.name).toBe(updatedRule.name));
  expect(screen.getByRole('heading', { name: 'Create policy' })).toBeVisible();
  expect(screen.getByText(updatedRule.name)).toBeVisible();
});

it('prevents inline creation of a second fallback and allows it after removal', async () => {
  const user = userEvent.setup();
  const fallback = fallbackRule('01990aa3-4b4c-7000-8000-000000000010', 'Primary fallback');
  render(
    <PolicyEditor
      policy={null}
      open
      onOpenChange={() => {}}
      onSubmit={async () => {}}
      pending={false}
      keys={[]}
      rules={[fallback]}
      ruleComposer={{
        catalog,
        usageByRuleId: new Map(),
        createPending: false,
        updatePending: false,
        create: async () => fallback,
        update: async () => fallback,
      }}
    />,
  );
  await user.click(screen.getByRole('button', { name: 'Add existing rule' }));
  await user.click(screen.getByRole('option', { name: /Primary fallback/ }));
  await user.click(screen.getByRole('button', { name: 'Create rule' }));
  expect(screen.getByRole('button', { name: 'Model fallbacks' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Parameter support' })).toBeEnabled();
  await user.click(screen.getByRole('button', { name: 'Back to policy' }));
  await user.click(screen.getByRole('button', { name: 'Remove Primary fallback' }));
  await user.click(screen.getByRole('button', { name: 'Create rule' }));
  expect(screen.getByRole('button', { name: 'Model fallbacks' })).toBeEnabled();
});
