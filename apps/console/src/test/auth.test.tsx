import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import App from '@/App';
import { ORG, server } from './msw';

function renderAt(path: string) {
  window.history.replaceState(null, '', path);
  return render(<App />);
}

const now = '2026-01-01T00:00:00Z';
const ORG2 = { id: 'org-2', name: 'Beta Corp', personal_for: null, created_at: now, updated_at: now, deleted_at: null };

// Enrollment must return at least two orgs for the picker UI to render at all —
// with a single org the picker auto-selects it. These tests opt into two orgs.
function withTwoOrgs() {
  server.use(
    http.get('/v1/auth/me', () =>
      HttpResponse.json({
        user_id: 'user-1',
        email: 'dev@example.com',
        name: 'Dev',
        instance_admin: false,
        orgs: [ORG.id, ORG2.id],
      }),
    ),
    http.get('/v1/enroll', () => HttpResponse.json({ orgs: [ORG, ORG2], personal_org_id: ORG.id })),
    // Workspaces are org-scoped via the X-Org-Id header. Serving different rows
    // per org lets the tests detect stale cross-org cache leaks.
    http.get('/v1/org/workspaces', ({ request }) => {
      const org = request.headers.get('X-Org-Id');
      if (org === ORG.id) {
        return HttpResponse.json([
           { id: 'ws-acme', org_id: ORG.id, name: 'Acme Production', slug: 'acme-production', created_at: now, updated_at: now, deleted_at: null },
        ]);
      }
      if (org === ORG2.id) {
        return HttpResponse.json([
           { id: 'ws-beta', org_id: ORG2.id, name: 'Beta Staging', slug: 'beta-staging', created_at: now, updated_at: now, deleted_at: null },
        ]);
      }
      return new HttpResponse(null, { status: 403 });
    }),
    // /org now defaults into a workspace, so its detail endpoint must resolve too.
    http.get('/v1/org/workspaces/:workspaceRef', ({ params }) => {
      const rows = {
        'ws-acme': { id: 'ws-acme', org_id: ORG.id, name: 'Acme Production', slug: 'acme-production', created_at: now, updated_at: now, deleted_at: null },
        'ws-beta': { id: 'ws-beta', org_id: ORG2.id, name: 'Beta Staging', slug: 'beta-staging', created_at: now, updated_at: now, deleted_at: null },
        'acme-production': { id: 'ws-acme', org_id: ORG.id, name: 'Acme Production', slug: 'acme-production', created_at: now, updated_at: now, deleted_at: null },
        'beta-staging': { id: 'ws-beta', org_id: ORG2.id, name: 'Beta Staging', slug: 'beta-staging', created_at: now, updated_at: now, deleted_at: null },
      } as const;
      const ws = rows[params.workspaceRef as keyof typeof rows];
      return ws ? HttpResponse.json(ws) : new HttpResponse(null, { status: 404 });
    }),
  );
}

describe('sign-in gate', () => {
  it('shows the login page to unauthenticated users', async () => {
    server.use(
      http.get('/v1/auth/me', () => new HttpResponse(null, { status: 401 })),
      http.get('/v1/instance/oss/claim', () => HttpResponse.json({ claimed: true })),
    );
    renderAt('/org');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.queryByText('Organization Overview')).not.toBeInTheDocument();
  });
});

describe('sign-in landing', () => {
  it('lands in the last-selected org', async () => {
    localStorage.setItem('airllm_org_id', ORG.id);
    renderAt('/');
    expect(await screen.findByRole('heading', { level: 1, name: 'Production' })).toBeInTheDocument();
  });

  it('lands on the picker when no org was selected before', async () => {
    withTwoOrgs();
    renderAt('/');
    expect(await screen.findByRole('heading', { name: 'Select Organization' })).toBeInTheDocument();
  });
});

describe('instance admin gate', () => {
  it('redirects non-admin users from /instance to the org console', async () => {
    localStorage.setItem('airllm_org_id', ORG.id);
    renderAt('/instance');
    // Default handlers: instance_admin is false, so the org console renders instead.
    expect(await screen.findByRole('heading', { level: 1, name: 'Production' })).toBeInTheDocument();
    expect(window.location.pathname).not.toBe('/instance');
  });
});

describe('organization picker', () => {
  it('falls back to the picker when the stored org is no longer a membership', async () => {
    withTwoOrgs();
    localStorage.setItem('airllm_org_id', 'org-gone');
    renderAt('/org');
    expect(await screen.findByRole('heading', { name: 'Select Organization' })).toBeInTheDocument();
    expect(screen.getByText(ORG.name)).toBeInTheDocument();
    expect(screen.getByText(ORG2.name)).toBeInTheDocument();
  });

  it('lands in the org after picking one, defaulting to its first workspace', async () => {
    withTwoOrgs();
    const user = userEvent.setup();
    renderAt('/org');
    await user.click(await screen.findByRole('button', { name: new RegExp(ORG.name) }));
    // /org auto-picks a default workspace, so the workspace overview renders.
    expect(await screen.findByRole('heading', { level: 1, name: 'Acme Production' })).toBeInTheDocument();
    expect(localStorage.getItem('airllm_org_id')).toBe(ORG.id);
  });

  it('auto-selects the org when the user belongs to exactly one', async () => {
    // Default handlers: single ORG membership, no stored selection.
    renderAt('/org');
    // The single org is auto-picked, then /org defaults to its first workspace.
    expect(await screen.findByRole('heading', { level: 1, name: 'Production' })).toBeInTheDocument();
    expect(localStorage.getItem('airllm_org_id')).toBe(ORG.id);
  });
});

describe('switching organizations', () => {
  it('returns to the picker and drops the previous org\'s data', async () => {
    withTwoOrgs();
    localStorage.setItem('airllm_org_id', ORG.id);
    const user = userEvent.setup();
    renderAt('/org');

    // Signed in to org-1: its workspace is on screen (and in the query cache).
    expect(await screen.findByRole('heading', { level: 1, name: 'Acme Production' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Switch organization' }));
    expect(await screen.findByRole('heading', { name: 'Select Organization' })).toBeInTheDocument();
    expect(localStorage.getItem('airllm_org_id')).toBeNull();

    await user.click(screen.getByRole('button', { name: new RegExp(ORG2.name) }));

    // Org-2's default workspace renders and none of org-1's stale rows remain.
    expect(await screen.findByRole('heading', { level: 1, name: 'Beta Staging' })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText('Acme Production')).not.toBeInTheDocument();
    });
  });
});
