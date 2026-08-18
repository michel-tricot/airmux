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

function withTwoOrgs() {
  server.use(
    http.get('/api/v1/auth/me', () =>
      HttpResponse.json({
        user_id: 'user-1',
        email: 'dev@example.com',
        name: 'Dev',
        instance_role: null,
        orgs: [ORG.id, ORG2.id],
      }),
    ),
    http.get('/api/v1/enroll', () => HttpResponse.json({ orgs: [ORG, ORG2], personal_org_id: ORG.id, pending_invitations: [] })),
    http.get('/api/v1/orgs/:orgId/workspaces', ({ params }) => {
      if (params.orgId === ORG.id) {
        return HttpResponse.json([
          { id: 'ws-acme', org_id: ORG.id, name: 'Acme Production', slug: 'acme-production', created_at: now, updated_at: now, deleted_at: null },
        ]);
      }
      if (params.orgId === ORG2.id) {
        return HttpResponse.json([
          { id: 'ws-beta', org_id: ORG2.id, name: 'Beta Staging', slug: 'beta-staging', created_at: now, updated_at: now, deleted_at: null },
        ]);
      }
      return new HttpResponse(null, { status: 403 });
    }),
    http.get('/api/v1/orgs/:orgId/workspaces/:workspaceRef', ({ params }) => {
      const rows = {
        'ws-acme': {
          id: 'ws-acme',
          org_id: ORG.id,
          name: 'Acme Production',
          slug: 'acme-production',
          created_at: now,
          updated_at: now,
          deleted_at: null,
        },
        'ws-beta': { id: 'ws-beta', org_id: ORG2.id, name: 'Beta Staging', slug: 'beta-staging', created_at: now, updated_at: now, deleted_at: null },
        'acme-production': {
          id: 'ws-acme',
          org_id: ORG.id,
          name: 'Acme Production',
          slug: 'acme-production',
          created_at: now,
          updated_at: now,
          deleted_at: null,
        },
        'beta-staging': {
          id: 'ws-beta',
          org_id: ORG2.id,
          name: 'Beta Staging',
          slug: 'beta-staging',
          created_at: now,
          updated_at: now,
          deleted_at: null,
        },
      } as const;
      const workspace = rows[params.workspaceRef as keyof typeof rows];
      return workspace?.org_id === params.orgId ? HttpResponse.json(workspace) : new HttpResponse(null, { status: 404 });
    }),
  );
}

describe('sign-in gate', () => {
  it('shows the login page to unauthenticated users', async () => {
    server.use(
      http.get('/api/v1/auth/me', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/v1/instance/oss/claim', () => HttpResponse.json({ claimed: true })),
    );
    renderAt('/org');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.queryByText('Organization Overview')).not.toBeInTheDocument();
  });

  it('shows a service error when the session endpoint is unavailable', async () => {
    server.use(
      http.get('/api/v1/auth/me', () => new HttpResponse(null, { status: 503 })),
      http.get('/api/v1/instance/oss/claim', () => HttpResponse.json({ claimed: true })),
    );
    renderAt('/org');
    expect(await screen.findByRole('alert')).toHaveTextContent('Control plane unreachable');
    expect(screen.getByRole('button', { name: /retry now/i })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Sign in' })).not.toBeInTheDocument();
  });

  it('signs in without requiring the signup-only name field', async () => {
    window.localStorage.setItem('airllm_org_id', ORG.id);
    server.use(
      http.get('/api/v1/auth/me', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/v1/instance/oss/claim', () => HttpResponse.json({ claimed: true })),
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json({
          user_id: 'user-1',
          email: 'dev@example.com',
          name: 'Dev',
          instance_role: null,
          orgs: [ORG.id],
        }),
      ),
    );
    const user = userEvent.setup();
    renderAt('/');

    await user.type(await screen.findByLabelText('Email'), 'dev@example.com');
    await user.type(screen.getByLabelText('Password'), 'secret');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Production' })).toBeInTheDocument();
  });

  it.each(['unknown account', 'incorrect password'])('keeps the sign-in error visible for an %s', async () => {
    server.use(
      http.get('/api/v1/auth/me', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/v1/instance/oss/claim', () => HttpResponse.json({ claimed: true })),
      http.post('/api/v1/auth/login', () => HttpResponse.json({ detail: 'Invalid credentials' }, { status: 401 })),
    );
    const user = userEvent.setup();
    renderAt('/');

    await user.type(await screen.findByLabelText('Email'), 'unknown@example.com');
    await user.type(screen.getByLabelText('Password'), 'incorrect-password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Sign in failed. Check your email and password.');
    expect(screen.getByText('Incorrect email or password')).toBeInTheDocument();
  });

  it('clears the selected organization when signing out', async () => {
    let signedIn = true;
    window.localStorage.setItem('airllm_org_id', ORG.id);
    server.use(
      http.get('/api/v1/auth/me', () =>
        signedIn
          ? HttpResponse.json({ user_id: 'user-1', email: 'dev@example.com', name: 'Dev', instance_role: null, orgs: [ORG.id] })
          : new HttpResponse(null, { status: 401 }),
      ),
      http.post('/api/v1/auth/logout', () => {
        signedIn = false;
        return HttpResponse.json({ id: 'session-1', status: 'deleted' });
      }),
      http.get('/api/v1/instance/oss/claim', () => HttpResponse.json({ claimed: true })),
    );
    const user = userEvent.setup();
    renderAt('/org');

    await user.click(await screen.findByRole('button', { name: 'Sign out' }));

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(window.localStorage.getItem('airllm_org_id')).toBeNull();
  });
});

describe('sign-in landing', () => {
  it('lands in the last-selected org', async () => {
    window.localStorage.setItem('airllm_org_id', ORG.id);
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
    window.localStorage.setItem('airllm_org_id', ORG.id);
    renderAt('/instance');
    expect(await screen.findByRole('heading', { level: 1, name: 'Production' })).toBeInTheDocument();
    expect(window.location.pathname).not.toBe('/instance');
  });
});

describe('organization picker', () => {
  it('shows an enrollment error instead of an empty organization picker', async () => {
    window.localStorage.setItem('airllm_org_id', ORG.id);
    server.use(http.get('/api/v1/enroll', () => new HttpResponse(null, { status: 503 })));
    renderAt('/org');
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load your organizations');
    expect(screen.queryByRole('heading', { name: 'Select Organization' })).not.toBeInTheDocument();
  });

  it('falls back to the picker when the stored org is no longer a membership', async () => {
    withTwoOrgs();
    window.localStorage.setItem('airllm_org_id', 'org-gone');
    renderAt('/org');
    expect(await screen.findByRole('heading', { name: 'Select Organization' })).toBeInTheDocument();
    await waitFor(() => expect(window.localStorage.getItem('airllm_org_id')).toBeNull());
    expect(screen.getByText(ORG.name)).toBeInTheDocument();
    expect(screen.getByText(ORG2.name)).toBeInTheDocument();
  });

  it('lands in the org after picking one, defaulting to its first workspace', async () => {
    withTwoOrgs();
    const user = userEvent.setup();
    renderAt('/org');
    await user.click(await screen.findByRole('button', { name: new RegExp(ORG.name) }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Acme Production' })).toBeInTheDocument();
    expect(window.localStorage.getItem('airllm_org_id')).toBe(ORG.id);
  });

  it('auto-selects the org when the user belongs to exactly one', async () => {
    renderAt('/org');
    expect(await screen.findByRole('heading', { level: 1, name: 'Production' })).toBeInTheDocument();
    expect(window.localStorage.getItem('airllm_org_id')).toBe(ORG.id);
  });
});

describe('switching organizations', () => {
  it("returns to the picker and drops the previous org's data", async () => {
    withTwoOrgs();
    window.localStorage.setItem('airllm_org_id', ORG.id);
    const user = userEvent.setup();
    renderAt('/org');

    expect(await screen.findByRole('heading', { level: 1, name: 'Acme Production' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Switch organization' }));
    expect(await screen.findByRole('heading', { name: 'Select Organization' })).toBeInTheDocument();
    expect(window.localStorage.getItem('airllm_org_id')).toBeNull();

    await user.click(screen.getByRole('button', { name: new RegExp(ORG2.name) }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Beta Staging' })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText('Acme Production')).not.toBeInTheDocument();
    });
  });
});
