import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '@/App';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { ORG, WORKSPACES, server } from './msw';

const now = '2026-01-01T00:00:00Z';

beforeEach(() => {
  window.localStorage.setItem('airllm_org_id', ORG.id);
});

describe('provider icons', () => {
  it('removes active content from taxonomy SVG markup', async () => {
    server.use(
      http.get('/v1/taxonomy', () =>
        HttpResponse.json({
          models: [],
          providers: [
            {
              id: 'provider-1',
              name: 'malicious',
              kind: 'openai_compatible',
              base_url: 'https://example.com/v1',
              icon: '<svg viewBox="0 0 24 24" onload="alert(1)"><script>alert(1)</script><image href="https://tracker.example/pixel" /><path style="filter:url(https://tracker.example/filter)" d="M0 0h24v24H0z" /></svg>',
              param_aliases: {},
              accepted_params: null,
              params_closed: false,
              created_at: now,
              updated_at: now,
              deleted_at: null,
            },
          ],
        }),
      ),
    );
    window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}/byok`);
    render(<App />);

    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Add Key' }));
    const provider = await screen.findByRole('radio', { name: 'malicious' });
    expect(provider.querySelector('script')).toBeNull();
    expect(provider.querySelector('[onload]')).toBeNull();
    expect(provider.querySelector('[href]')).toBeNull();
    expect(provider.querySelector('[style]')).toBeNull();
  });
});

describe('show-once keys', () => {
  it('reports clipboard failures and keeps manual copy available', async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('blocked'));
    render(<KeyRevealDialog open onOpenChange={() => undefined} token="secret-token" />);

    await user.click(screen.getByRole('button', { name: 'Copy key' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not copy the key');
    expect(screen.getByDisplayValue('secret-token')).toBeInTheDocument();
  });

  it('clears stale clipboard feedback before revealing a different key', async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('blocked'));
    const dialog = render(<KeyRevealDialog open onOpenChange={() => undefined} token="first-token" />);

    await user.click(screen.getByRole('button', { name: 'Copy key' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();

    dialog.rerender(<KeyRevealDialog open={false} onOpenChange={() => undefined} token={null} />);
    dialog.rerender(<KeyRevealDialog open onOpenChange={() => undefined} token="second-token" />);

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy key' })).toBeInTheDocument();
  });
});
