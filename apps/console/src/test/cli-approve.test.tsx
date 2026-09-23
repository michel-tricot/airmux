import type * as Api from '@workspace/api-client-react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import App from '@/App';
import { ORG, server } from './msw';

function renderAt(path: string) {
  window.history.replaceState(null, '', path);
  return render(<App />);
}

const REQUEST = {
  client_name: 'airmux CLI',
  requester: 'devbox.local',
  expires_at: '2030-01-01T00:00:00Z',
  can_approve_instance: false,
};

function withPendingRequest(expectedCode: string) {
  server.use(
    http.get('/api/v1/auth/cli/request', ({ request }) => {
      const code = new URL(request.url).searchParams.get('code');
      if (code !== expectedCode) return new HttpResponse(null, { status: 404 });
      return HttpResponse.json<{ data: Api.CliAuthRequestOut }>({ data: REQUEST });
    }),
  );
}

describe('CLI device sign-in approval', () => {
  it('shows the login page first when visiting /cli unauthenticated', async () => {
    server.use(
      http.get('/api/v1/auth/me', () => new HttpResponse(null, { status: 401 })),
      http.get('/api/v1/instance/oss/claim', () => HttpResponse.json<{ data: Api.ClaimOut }>({ data: { claimed: true, public_signup: true } })),
    );
    renderAt('/cli?code=ABCD-1234');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.queryByText('Authorize CLI login')).not.toBeInTheDocument();
  });

  it('shows the approval prompt with the request details for a signed-in user', async () => {
    withPendingRequest('ABCD-1234');
    renderAt('/cli?code=ABCD-1234');
    expect(await screen.findByRole('heading', { name: 'Authorize CLI login' })).toBeInTheDocument();
    expect(await screen.findByText(REQUEST.client_name)).toBeInTheDocument();
    expect(screen.getByText(REQUEST.requester)).toBeInTheDocument();
    expect(await screen.findByLabelText('Access scope')).toHaveTextContent(`Organization: ${ORG.name}`);
    expect(screen.getByRole('button', { name: 'Authorize' })).toBeEnabled();
  });

  it('approves the request against the control plane and shows confirmation', async () => {
    withPendingRequest('ABCD-1234');
    let approveBody: unknown = null;
    server.use(
      http.post('/api/v1/auth/cli/approve', async ({ request }) => {
        approveBody = await request.json();
        return HttpResponse.json<{ data: Api.CliAuthApprovedOut }>({ data: { status: 'approved', client_name: 'test-cli' } });
      }),
    );
    const user = userEvent.setup();
    renderAt('/cli?code=ABCD-1234');
    await user.click(await screen.findByRole('button', { name: 'Authorize' }));
    expect(await screen.findByText(/Approved\. Return to your terminal/)).toBeInTheDocument();
    expect(approveBody).toEqual({ user_code: 'ABCD-1234', scope: 'org', org_id: ORG.id });
  });

  it('allows an instance admin to approve instance access', async () => {
    server.use(
      http.get('/api/v1/auth/cli/request', () =>
        HttpResponse.json<{ data: Api.CliAuthRequestOut }>({ data: { ...REQUEST, can_approve_instance: true } }),
      ),
    );
    let approveBody: unknown = null;
    server.use(
      http.post('/api/v1/auth/cli/approve', async ({ request }) => {
        approveBody = await request.json();
        return HttpResponse.json<{ data: Api.CliAuthApprovedOut }>({ data: { status: 'approved', client_name: 'test-cli' } });
      }),
    );
    const user = userEvent.setup();
    renderAt('/cli?code=ABCD-1234');

    expect(await screen.findByLabelText('Access scope')).toHaveTextContent('Instance');
    await user.click(screen.getByRole('button', { name: 'Authorize' }));

    expect(await screen.findByText(/Approved\. Return to your terminal/)).toBeInTheDocument();
    expect(approveBody).toEqual({ user_code: 'ABCD-1234', scope: 'instance' });
  });

  it('shows a clear error and the code form for an unknown code', async () => {
    withPendingRequest('GOOD-CODE');
    renderAt('/cli?code=WRONG-CODE');
    expect(await screen.findByText('No pending login with this code. Check your terminal, or run airmux login again.')).toBeInTheDocument();
    expect(screen.getByLabelText('Code from your terminal')).toBeInTheDocument();
  });

  it('shows the expiry message for an expired code and recovers after re-entry', async () => {
    server.use(
      http.get('/api/v1/auth/cli/request', ({ request }) => {
        const code = new URL(request.url).searchParams.get('code');
        if (code === 'FRESH-CODE') return HttpResponse.json<{ data: Api.CliAuthRequestOut }>({ data: REQUEST });
        return new HttpResponse(null, { status: 410 });
      }),
    );
    const user = userEvent.setup();
    renderAt('/cli?code=OLD-CODE');
    expect(await screen.findByText('This login request expired. Run airmux login again.')).toBeInTheDocument();

    const input = screen.getByLabelText('Code from your terminal');
    await user.clear(input);
    await user.type(input, 'FRESH-CODE');
    await user.click(screen.getByRole('button', { name: 'Look up request' }));
    expect(await screen.findByText(REQUEST.client_name)).toBeInTheDocument();
  });

  it('prompts for a code when /cli is visited without one', async () => {
    renderAt('/cli');
    expect(await screen.findByRole('heading', { name: 'Authorize CLI login' })).toBeInTheDocument();
    expect(screen.getByLabelText('Code from your terminal')).toBeInTheDocument();
  });

  it('does not treat routes that merely start with cli as approval routes', async () => {
    window.localStorage.setItem('airmux_org_id', ORG.id);
    renderAt('/client');
    expect(await screen.findByRole('heading', { level: 1, name: 'Usage' })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/org');
  });
});
