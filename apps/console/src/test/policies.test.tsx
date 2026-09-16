import type * as Api from '@workspace/api-client-react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, server } from './msw';

const now = '2026-01-01T00:00:00Z';

function rule(id: string, name: string): Api.RuleOut {
  return {
    id: `rule-${id}`,
    org_id: ORG.id,
    workspace_id: WORKSPACES[0].id,
    name: `${name} rule`,
    definition: { match: { kind: 'all_requests' }, action: { kind: 'deny', message: `${name} denied` } },
    created_at: now,
    updated_at: now,
    deleted_at: null,
  };
}

function policy(id: string, name: string, priority: number): Api.PolicyOut {
  return {
    id,
    org_id: ORG.id,
    workspace_id: WORKSPACES[0].id,
    name,
    enabled: true,
    priority,
    definition: {
      target: { kind: 'workspace' },
      rule_ids: [`rule-${id}`],
    },
    created_at: now,
    updated_at: now,
    deleted_at: null,
  };
}

const initialPolicies = [policy('policy-1', 'First', 0), policy('policy-2', 'Second', 1), policy('policy-3', 'Third', 2)];
const initialRules = [rule('policy-1', 'First'), rule('policy-2', 'Second'), rule('policy-3', 'Third')];

function renderPolicies() {
  window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}/policies`);
  return render(<App />);
}

function policyRows() {
  return within(screen.getByRole('table'))
    .getAllByRole('row')
    .filter((row) => row.parentElement?.tagName === 'TBODY');
}

function mockPolicyRowLayout() {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const row = this.closest('tr');
    const index = row ? Array.from(row.parentElement?.children ?? []).indexOf(row) : 0;
    const top = Math.max(index, 0) * 48;
    return {
      x: 0,
      y: top,
      top,
      left: 0,
      right: 800,
      bottom: top + 48,
      width: 800,
      height: 48,
      toJSON: () => ({}),
    };
  });
}

async function dragBelowNext(handle: HTMLElement) {
  fireEvent.pointerDown(handle, { button: 0, clientX: 16, clientY: 24, isPrimary: true, pointerId: 1 });
  fireEvent.pointerMove(document, { clientX: 16, clientY: 32, isPrimary: true, pointerId: 1 });
  await waitFor(() => expect(handle.closest('tr')).toHaveClass('opacity-70'));
  fireEvent.pointerMove(document, { clientX: 16, clientY: 72, isPrimary: true, pointerId: 1 });
  await waitFor(() => expect(policyRows()[1].style.transform).toContain('translate3d'));
  fireEvent.pointerUp(document, { clientX: 16, clientY: 72, isPrimary: true, pointerId: 1 });
}

beforeEach(() => window.localStorage.setItem('airmux_org_id', ORG.id));

describe('workspace policies', () => {
  it('shows reusable rules and their policy usage in a focused library', async () => {
    const user = userEvent.setup();
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/rules', () =>
        HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: initialPolicies }),
      ),
    );
    renderPolicies();

    await user.click(await screen.findByRole('tab', { name: 'Rule library' }));

    expect(screen.getByText('First rule')).toBeVisible();
    expect(screen.getAllByText('1 policy')).toHaveLength(3);
    expect(screen.getByRole('button', { name: 'First rule is used by policies' })).toBeDisabled();
  });

  it('does not treat rule usage as zero when policies are unavailable', async () => {
    const user = userEvent.setup();
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/rules', () =>
        HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () => HttpResponse.json({ detail: 'unavailable' }, { status: 503 })),
    );
    renderPolicies();

    await user.click(await screen.findByRole('tab', { name: 'Rule library' }));

    expect(await screen.findByText('Usage unavailable')).toBeVisible();
    expect(screen.getByRole('button', { name: 'First rule usage is unavailable' })).toBeDisabled();
  });

  it('presents model names with the shared catalog model style', async () => {
    const user = userEvent.setup();
    const modelRule: Api.RuleOut = {
      ...rule('policy-1', 'Approved models'),
      definition: { match: { kind: 'all_requests' }, action: { kind: 'models', names: ['openai/gpt-4o'] } },
    };
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/rules', () =>
        HttpResponse.json<{ data: Api.RuleOut[] }>({ data: [modelRule] }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: [initialPolicies[0]] }),
      ),
    );
    renderPolicies();

    await user.click(await screen.findByRole('tab', { name: 'Rule library' }));

    expect(screen.getByText('openai/gpt-4o')).toHaveClass('font-mono');
  });

  it('keeps policy editing available when only the model catalog is unavailable', async () => {
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/rules', () =>
        HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: initialPolicies }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/taxonomy', () => HttpResponse.json({ detail: 'unavailable' }, { status: 503 })),
    );
    renderPolicies();

    expect(await screen.findByText('First')).toBeVisible();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create rule' })).toBeDisabled());
    expect(screen.getByRole('button', { name: 'Create policy' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Edit First' })).toBeEnabled();
  });

  it('keeps rule editing available when only inference keys are unavailable', async () => {
    const user = userEvent.setup();
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/rules', () =>
        HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: initialPolicies }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/inference-keys', () =>
        HttpResponse.json({ detail: 'unavailable' }, { status: 503 }),
      ),
    );
    renderPolicies();

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create rule' })).toBeEnabled());
    expect(screen.getByRole('button', { name: 'Create policy' })).toBeDisabled();
    await user.click(screen.getByRole('tab', { name: 'Rule library' }));
    expect(screen.getByRole('button', { name: 'Edit First rule' })).toBeEnabled();
  });

  it('allows policy creation before the rule library has any rules', async () => {
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () => HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: [] })),
    );
    renderPolicies();

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create policy' })).toBeEnabled());
  });

  it('creates a shared rule from policy creation and keeps it when the policy is canceled', async () => {
    const user = userEvent.setup();
    let submittedRule: Api.RuleCreate | undefined;
    let workspaceRules: Api.RuleOut[] = [];
    const createdRule: Api.RuleOut = {
      id: '01990aa3-4b4c-7000-8000-000000000010',
      org_id: ORG.id,
      workspace_id: WORKSPACES[0].id,
      name: 'Inline strict parameters',
      definition: { match: { kind: 'all_requests' }, action: { kind: 'strict_parameters' } },
      created_at: now,
      updated_at: now,
      deleted_at: null,
    };
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/rules', () =>
        HttpResponse.json<{ data: Api.RuleOut[] }>({ data: workspaceRules }),
      ),
      http.post('/api/v1/organizations/:orgId/workspaces/:workspaceRef/rules', async ({ request }) => {
        submittedRule = (await request.json()) as Api.RuleCreate;
        workspaceRules = [createdRule];
        return HttpResponse.json<{ data: Api.RuleOut }>({ data: createdRule });
      }),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () => HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: [] })),
    );
    renderPolicies();

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create policy' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Create policy' }));
    await user.type(screen.getByLabelText('Policy name'), 'Unsaved policy');
    await user.click(screen.getByRole('button', { name: 'Create rule' }));
    await user.click(screen.getByRole('button', { name: 'Parameter support' }));
    await user.type(screen.getByLabelText('Rule name'), createdRule.name);
    await user.click(screen.getByRole('button', { name: 'Create and add rule' }));

    await waitFor(() => expect(submittedRule?.name).toBe(createdRule.name));
    expect(screen.getByText(createdRule.name)).toBeVisible();
    expect(screen.getByText('New')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await user.click(screen.getByRole('tab', { name: 'Rule library' }));

    expect(await screen.findByText(createdRule.name)).toBeVisible();
  });

  it('chooses a rule type before opening its focused form', async () => {
    const user = userEvent.setup();
    renderPolicies();

    await user.click(await screen.findByRole('button', { name: 'Create rule' }));
    expect(screen.getByRole('heading', { name: 'Choose a rule type' })).toBeVisible();
    expect(screen.queryByLabelText('Rule name')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Budget' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Allowed models' }));
    expect(screen.getByRole('heading', { name: 'Create allowed models rule' })).toBeVisible();
    expect(screen.getByLabelText('Rule name')).toBeVisible();
    expect(screen.queryByRole('combobox', { name: 'Rule action' })).not.toBeInTheDocument();
  });

  it('keeps policy rows compact and reveals rule details in a tooltip', async () => {
    const user = userEvent.setup();
    const multiRulePolicy = {
      ...policy('policy-1', 'Production', 0),
      definition: { target: { kind: 'workspace' } as const, rule_ids: initialRules.map((item) => item.id) },
    };
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/rules', () =>
        HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: [multiRulePolicy] }),
      ),
    );
    renderPolicies();

    const summary = await screen.findByLabelText('3 rules: First rule, Second rule, Third rule');
    expect(summary).toHaveTextContent('First rule +2 more');
    expect(summary.closest('tr')).toHaveClass('h-16');
    expect(summary).not.toHaveClass('cursor-help');

    await user.hover(summary);
    expect(await screen.findByText('Rules')).toBeVisible();
    expect(await screen.findByText('First denied')).toBeVisible();
    expect(screen.getByText('Second denied')).toBeVisible();
    expect(screen.getByText('Third denied')).toBeVisible();
  });

  it('closes rule tooltips while reordering policies', async () => {
    const user = userEvent.setup();
    mockPolicyRowLayout();
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/rules', () =>
        HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: initialPolicies }),
      ),
    );
    renderPolicies();

    const summary = await screen.findByLabelText('1 rule: First rule');
    const handle = screen.getByRole('button', { name: 'Reorder First' });
    fireEvent.pointerDown(handle, { button: 0, clientX: 16, clientY: 24, isPrimary: true, pointerId: 1 });
    fireEvent.pointerMove(document, { clientX: 16, clientY: 32, isPrimary: true, pointerId: 1 });
    await waitFor(() => expect(handle.closest('tr')).toHaveClass('opacity-70'));
    await user.hover(summary);
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(screen.queryByText('First denied')).not.toBeInTheDocument();
    fireEvent.pointerUp(document, { clientX: 16, clientY: 32, isPrimary: true, pointerId: 1 });
  });

  it('keeps the dragged policy row on the table axis', async () => {
    mockPolicyRowLayout();
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/rules', () =>
        HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: initialPolicies }),
      ),
    );
    renderPolicies();

    const handle = await screen.findByRole('button', { name: 'Reorder First' });
    fireEvent.pointerDown(handle, { button: 0, clientX: 16, clientY: 24, isPrimary: true, pointerId: 1 });
    fireEvent.pointerMove(document, { clientX: 96, clientY: 32, isPrimary: true, pointerId: 1 });
    await waitFor(() => expect(handle.closest('tr')).toHaveClass('opacity-70'));
    const tableContainer = handle.closest('table')?.parentElement?.parentElement;
    expect(tableContainer).toHaveClass('overflow-hidden');
    expect(tableContainer?.className).toContain('[&>div]:overflow-hidden');
    expect(handle.closest('tr')?.style.transform).toMatch(/^translate3d\(0px, /);
    expect(handle.closest('tr')?.style.transform).not.toContain('scale');
    expect(screen.getAllByText('First')).toHaveLength(1);
    fireEvent.pointerUp(document, { clientX: 96, clientY: 32, isPrimary: true, pointerId: 1 });
    await waitFor(() => expect(tableContainer).toHaveClass('overflow-auto'));
  });

  it('shifts rows while dragging and saves the complete order', async () => {
    mockPolicyRowLayout();
    let policies = initialPolicies;
    let submittedOrder: string[] | undefined;
    let reorderCompleted = false;
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/rules', () =>
        HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: policies }),
      ),
      http.put('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies/order', async ({ request }) => {
        submittedOrder = ((await request.json()) as Api.PolicyOrder).policy_ids;
        await new Promise((resolve) => setTimeout(resolve, 250));
        const policiesById = new Map(policies.map((item) => [item.id, item]));
        policies = submittedOrder.map((id, priority) => ({ ...policiesById.get(id)!, priority }));
        reorderCompleted = true;
        return HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: policies });
      }),
    );
    renderPolicies();

    const firstHandle = await screen.findByRole('button', { name: 'Reorder First' });
    await dragBelowNext(firstHandle);

    expect(policyRows().map((row) => within(row).getAllByRole('cell')[1].textContent)).toEqual(['Second1 rule', 'First1 rule', 'Third1 rule']);
    expect(policyRows().map((row) => within(row).getAllByRole('cell')[4].textContent)).toEqual(['0', '1', '2']);
    await waitFor(() => expect(submittedOrder).toEqual(['policy-2', 'policy-1', 'policy-3']));
    await waitFor(() => expect(reorderCompleted).toBe(true));
  });

  it('reorders policies with the keyboard', async () => {
    mockPolicyRowLayout();
    let submittedOrder: string[] | undefined;
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/rules', () =>
        HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: initialPolicies }),
      ),
      http.put('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies/order', async ({ request }) => {
        submittedOrder = ((await request.json()) as Api.PolicyOrder).policy_ids;
        const policiesById = new Map(initialPolicies.map((item) => [item.id, item]));
        return HttpResponse.json<{ data: Api.PolicyOut[] }>({
          data: submittedOrder.map((id, priority) => ({ ...policiesById.get(id)!, priority })),
        });
      }),
    );
    renderPolicies();

    const firstHandle = await screen.findByRole('button', { name: 'Reorder First' });
    firstHandle.focus();
    fireEvent.keyDown(firstHandle, { key: ' ', code: 'Space' });
    await waitFor(() => expect(firstHandle.closest('tr')).toHaveClass('opacity-70'));
    fireEvent.keyDown(firstHandle, { key: 'ArrowDown', code: 'ArrowDown' });
    fireEvent.keyDown(firstHandle, { key: ' ', code: 'Space' });

    await waitFor(() => expect(submittedOrder).toEqual(['policy-2', 'policy-1', 'policy-3']));
  });

  it('restores the prior order when saving fails', async () => {
    mockPolicyRowLayout();
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/rules', () =>
        HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: initialPolicies }),
      ),
      http.put('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies/order', async () => {
        await new Promise((resolve) => setTimeout(resolve, 100));
        return HttpResponse.json({ detail: 'failed' }, { status: 500 });
      }),
    );
    renderPolicies();

    await dragBelowNext(await screen.findByRole('button', { name: 'Reorder First' }));
    expect(policyRows().map((row) => within(row).getAllByRole('cell')[1].textContent)).toEqual(['Second1 rule', 'First1 rule', 'Third1 rule']);
    await waitFor(() =>
      expect(policyRows().map((row) => within(row).getAllByRole('cell')[1].textContent)).toEqual(['First1 rule', 'Second1 rule', 'Third1 rule']),
    );
  });

  it('does not show reorder controls to a policy viewer', async () => {
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/rules', () =>
        HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules }),
      ),
      http.get('/api/v1/auth/permissions', () =>
        HttpResponse.json<{ data: Api.MyPermissionsOut }>({ data: { permissions: ['organizations.read', 'workspaces.read', 'policies.read'] } }),
      ),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: initialPolicies }),
      ),
    );

    renderPolicies();

    expect(await screen.findByText('First')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Reorder/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Drag policies/)).not.toBeInTheDocument();
  });
});

it('shows workspace, principal, and key policies when inspecting an inference key', async () => {
  const user = userEvent.setup();
  const key: Api.InferenceKeyOut = {
    id: 'key-1',
    org_id: ORG.id,
    workspace_id: WORKSPACES[0].id,
    user_id: 'principal-1',
    label: 'Application',
    prefix: 'sk-inf',
    revoked: false,
    created_at: now,
    updated_at: now,
    deleted_at: null,
  };
  const policies: Api.PolicyOut[] = [
    policy('workspace', 'Workspace restriction', 0),
    {
      ...policy('user', 'Principal restriction', 1),
      definition: { target: { kind: 'selected_users', user_ids: [key.user_id] }, rule_ids: ['rule-user'] },
    },
    { ...policy('key', 'Key restriction', 2), definition: { target: { kind: 'selected_keys', key_ids: [key.id] }, rule_ids: ['rule-key'] } },
    { ...policy('other', 'Other principal', 3), definition: { target: { kind: 'selected_users', user_ids: ['other'] }, rule_ids: ['rule-other'] } },
    { ...policy('disabled', 'Disabled restriction', 4), enabled: false },
  ];
  server.use(
    http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/inference-keys', () => HttpResponse.json({ data: [key] })),
    http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/policies', () => HttpResponse.json({ data: policies })),
  );
  window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}/inference-keys`);
  render(<App />);
  await user.click(await screen.findByRole('button', { name: 'Inspect policies for Application' }));
  expect(screen.getByText('Workspace restriction')).toBeVisible();
  expect(screen.getByText('Principal restriction')).toBeVisible();
  expect(screen.getByText('Key restriction')).toBeVisible();
  expect(screen.queryByText('Other principal')).not.toBeInTheDocument();
  expect(screen.queryByText('Disabled restriction')).not.toBeInTheDocument();
});
