import type * as Api from '@workspace/api-client-react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, server } from './msw';
import { taxonomyProvider } from './fixtures';
beforeEach(() => window.localStorage.setItem('airmux_org_id', ORG.id));
describe('provider icons', () => {
  it('removes active content from taxonomy SVG markup', async () => {
    server.use(
      http.get(`/api/v1/organizations/${ORG.id}/workspaces/${WORKSPACES[0].slug}/taxonomy`, () =>
        HttpResponse.json<{ data: Api.TaxonomyOut }>({
          data: {
            models: [],
            providers: [
              taxonomyProvider(
                'provider-1',
                'malicious',
                '<svg viewBox="0 0 24 24" onload="alert(1)"><script>alert(1)</script><image href="https://tracker.example/pixel" /><path style="filter:url(https://tracker.example/filter)" d="M0 0h24v24H0z" /></svg>',
              ),
            ],
          },
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

  it('supports arrow-key navigation between providers', async () => {
    server.use(
      http.get(`/api/v1/organizations/${ORG.id}/workspaces/${WORKSPACES[0].slug}/taxonomy`, () =>
        HttpResponse.json<{ data: Api.TaxonomyOut }>({
          data: {
            models: [],
            providers: [taxonomyProvider('provider-1', 'first'), taxonomyProvider('provider-2', 'second')],
          },
        }),
      ),
    );
    window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}/byok`);
    render(<App />);

    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Add Key' }));
    const first = await screen.findByRole('radio', { name: 'first' });
    const second = screen.getByRole('radio', { name: 'second' });
    await user.click(first);
    expect(first).toHaveFocus();
    await user.keyboard('{ArrowRight}');

    expect(second).toHaveFocus();
  });
});
