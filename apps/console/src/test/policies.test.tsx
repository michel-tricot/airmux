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
      target: { kind: 'all_keys' },
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

beforeEach(() => window.localStorage.setItem('airllm_org_id', ORG.id));

describe('workspace policies', () => {
  it('shows reusable rules and their policy usage in a focused library', async () => {
    const user = userEvent.setup();
    server.use(
      http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/rules', () => HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules })),
      http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: initialPolicies }),
      ),
    );
    renderPolicies();

    await user.click(await screen.findByRole('tab', { name: 'Rule library' }));

    expect(screen.getByText('First rule')).toBeVisible();
    expect(screen.getAllByText('1 policy')).toHaveLength(3);
    expect(screen.getByRole('button', { name: 'First rule is used by policies' })).toBeDisabled();
  });

  it('shifts rows while dragging and saves the complete order', async () => {
    mockPolicyRowLayout();
    let policies = initialPolicies;
    let submittedOrder: string[] | undefined;
    let reorderCompleted = false;
    server.use(
      http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/rules', () => HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules })),
      http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/policies', () => HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: policies })),
      http.put('/api/v1/orgs/:orgId/workspaces/:workspaceRef/policies/order', async ({ request }) => {
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
    firstHandle.focus();
    fireEvent.keyDown(firstHandle, { key: ' ', code: 'Space' });
    fireEvent.keyDown(firstHandle, { key: 'ArrowDown', code: 'ArrowDown' });
    fireEvent.keyDown(firstHandle, { key: ' ', code: 'Space' });
    expect(firstHandle.closest('tr')).not.toHaveClass('opacity-70');
    expect(submittedOrder).toBeUndefined();

    await dragBelowNext(firstHandle);

    expect(policyRows().map((row) => within(row).getAllByRole('cell')[1].textContent)).toEqual(['Second1 rule', 'First1 rule', 'Third1 rule']);
    expect(policyRows().map((row) => within(row).getAllByRole('cell')[4].textContent)).toEqual(['0', '1', '2']);
    await waitFor(() => expect(submittedOrder).toEqual(['policy-2', 'policy-1', 'policy-3']));
    await waitFor(() => expect(reorderCompleted).toBe(true));
  });

  it('restores the prior order when saving fails', async () => {
    mockPolicyRowLayout();
    server.use(
      http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/rules', () => HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules })),
      http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: initialPolicies }),
      ),
      http.put('/api/v1/orgs/:orgId/workspaces/:workspaceRef/policies/order', async () => {
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
      http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/rules', () => HttpResponse.json<{ data: Api.RuleOut[] }>({ data: initialRules })),
      http.get('/api/v1/auth/permissions', () =>
        HttpResponse.json<{ data: Api.MyPermissionsOut }>({ data: { permissions: ['organizations.read', 'workspaces.read', 'policies.read'] } }),
      ),
      http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef/policies', () =>
        HttpResponse.json<{ data: Api.PolicyOut[] }>({ data: initialPolicies }),
      ),
    );

    renderPolicies();

    expect(await screen.findByText('First')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Reorder/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Drag policies/)).not.toBeInTheDocument();
  });
});
