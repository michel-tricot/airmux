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
          { id: 'ws-acme', org_id: ORG.id, name: 'Acme Production', created_at: now, updated_at: now, deleted_at: null },
        ]);
      }
      if (org === ORG2.id) {
        return HttpResponse.json([
          { id: 'ws-beta', org_id: ORG2.id, name: 'Beta Staging', created_at: now, updated_at: now, deleted_at: null },
        ]);
      }
      return new HttpResponse(null, { status: 403 });
    }),
  );
}

describe('sign-in gate', () => {
  it('shows the login page to unauthenticated users', async () => {
    server.use(
      http.get('/v1/auth/me', () => new HttpResponse(null, { status: 401 })),
      http.get('/v1/instance/oss/claim', () => HttpResponse.json({ claimed: true })),
    );
    renderAt('/app');
    expect(await screen.findByRole('heading', { name: 'Sign in to Gateway' })).toBeInTheDocument();
    expect(screen.queryByText('Organization Overview')).not.toBeInTheDocument();
  });
});

describe('organization picker', () => {
  it('falls back to the picker when the stored org is no longer a membership', async () => {
    withTwoOrgs();
    localStorage.setItem('airllm_org_id', 'org-gone');
    renderAt('/app');
    expect(await screen.findByRole('heading', { name: 'Select Organization' })).toBeInTheDocument();
    expect(screen.getByText(ORG.name)).toBeInTheDocument();
    expect(screen.getByText(ORG2.name)).toBeInTheDocument();
  });

  it('lands on the org dashboard after picking an org', async () => {
    withTwoOrgs();
    const user = userEvent.setup();
    renderAt('/app');
    await user.click(await screen.findByRole('button', { name: new RegExp(ORG.name) }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Organization Overview' })).toBeInTheDocument();
    expect(await screen.findByText('Acme Production')).toBeInTheDocument();
    expect(localStorage.getItem('airllm_org_id')).toBe(ORG.id);
  });

  it('auto-selects the org when the user belongs to exactly one', async () => {
    // Default handlers: single ORG membership, no stored selection.
    renderAt('/app');
    expect(await screen.findByRole('heading', { level: 1, name: 'Organization Overview' })).toBeInTheDocument();
    expect(localStorage.getItem('airllm_org_id')).toBe(ORG.id);
  });
});

describe('switching organizations', () => {
  it('returns to the picker and drops the previous org\'s data', async () => {
    withTwoOrgs();
    localStorage.setItem('airllm_org_id', ORG.id);
    const user = userEvent.setup();
    renderAt('/app');

    // Signed in to org-1: its workspaces are on screen (and in the query cache).
    expect(await screen.findByText('Acme Production')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Switch organization' }));
    expect(await screen.findByRole('heading', { name: 'Select Organization' })).toBeInTheDocument();
    expect(localStorage.getItem('airllm_org_id')).toBeNull();

    await user.click(screen.getByRole('button', { name: new RegExp(ORG2.name) }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Organization Overview' })).toBeInTheDocument();

    // The dashboard shows org-2's data and none of org-1's stale rows.
    expect(await screen.findByText('Beta Staging')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText('Acme Production')).not.toBeInTheDocument();
    });
  });
});
