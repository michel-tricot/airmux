import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '@/App';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { Badge, Button, ConfirmButton } from '@/components/ui/elements';
import { ORG, WORKSPACES, server } from './msw';
import { Link } from 'wouter';

const now = '2026-01-01T00:00:00Z';
const themeCss = readFileSync(path.resolve(process.cwd(), 'src/index.css'), 'utf8');

function taxonomyProvider(id: string, name: string, icon: string | null = null) {
  return {
    id,
    name,
    kind: 'openai_compatible',
    base_url: `https://${name}.example/v1`,
    icon,
    param_aliases: {},
    accepted_params: null,
    params_closed: false,
    created_at: now,
    updated_at: now,
    deleted_at: null,
  };
}

beforeEach(() => {
  window.localStorage.setItem('airllm_org_id', ORG.id);
});

function themeValue(name: string) {
  return themeCss.match(new RegExp(`(?:^|[;{])\\s*${name}:\\s*([^;]+);`, 'm'))?.[1].trim();
}

describe('console theme', () => {
  it('keeps the violet accent across global and sidebar semantics', () => {
    expect(themeValue('--ring')).toBe('244 100% 68%');
    expect(themeValue('--primary')).toBe('244 100% 68%');
    expect(themeValue('--primary-foreground')).toBe('0 0% 100%');
    expect(themeValue('--sidebar-primary')).toBe('244 100% 68%');
    expect(themeValue('--sidebar-primary-foreground')).toBe('0 0% 100%');
    expect(themeValue('--sidebar-accent')).toBe('244 50% 16%');
    expect(themeValue('--sidebar-accent-foreground')).toBe('244 100% 85%');
    expect(themeCss).toContain('rgb(97 94 255 / 5%)');
  });

  it('keeps violet emphasis on primary controls', () => {
    render(
      <>
        <Button>Save</Button>
        <Badge>Active</Badge>
      </>,
    );

    expect(screen.getByRole('button', { name: 'Save' })).toHaveClass('shadow-primary/40');
    expect(screen.getByText('Active')).toHaveClass('shadow-primary/15');
  });
});

describe('provider icons', () => {
  it('removes active content from taxonomy SVG markup', async () => {
    server.use(
      http.get(`/api/v1/orgs/${ORG.id}/workspaces/${WORKSPACES[0].slug}/taxonomy`, () =>
        HttpResponse.json({
          models: [],
          providers: [
            taxonomyProvider(
              'provider-1',
              'malicious',
              '<svg viewBox="0 0 24 24" onload="alert(1)"><script>alert(1)</script><image href="https://tracker.example/pixel" /><path style="filter:url(https://tracker.example/filter)" d="M0 0h24v24H0z" /></svg>',
            ),
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

  it('supports arrow-key navigation between providers', async () => {
    server.use(
      http.get(`/api/v1/orgs/${ORG.id}/workspaces/${WORKSPACES[0].slug}/taxonomy`, () =>
        HttpResponse.json({
          models: [],
          providers: [taxonomyProvider('provider-1', 'first'), taxonomyProvider('provider-2', 'second')],
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

describe('show-once keys', () => {
  it('shows copied feedback before the clipboard write finishes', async () => {
    const user = userEvent.setup();
    let finishCopy: (() => void) | undefined;
    vi.spyOn(navigator.clipboard, 'writeText').mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finishCopy = resolve;
        }),
    );
    render(<KeyRevealDialog open onOpenChange={() => undefined} token="secret-token" />);

    await user.click(screen.getByRole('button', { name: 'Copy key' }));

    expect(screen.getByRole('button', { name: 'Copied' })).toHaveTextContent('Copied');
    finishCopy?.();
  });

  it('presents an explicit copy action without focusing the secret text', async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
    render(<KeyRevealDialog open onOpenChange={() => undefined} token="secret-token" />);

    const secret = screen.getByDisplayValue('secret-token');
    const copy = screen.getByRole('button', { name: 'Copy key' });
    expect(secret).not.toHaveFocus();
    expect(copy).toHaveTextContent('Copy key');

    await user.click(copy);

    expect(writeText).toHaveBeenCalledWith('secret-token');
    expect(screen.getByRole('button', { name: 'Copied' })).toHaveTextContent('Copied');
  });

  it('reports clipboard failures and keeps manual copy available', async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('blocked'));
    render(<KeyRevealDialog open onOpenChange={() => undefined} token="secret-token" />);

    await user.click(screen.getByRole('button', { name: 'Copy key' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not copy the key');
    expect(screen.getByDisplayValue('secret-token')).toHaveFocus();
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

describe('shared controls', () => {
  it('composes button styling onto navigation without nesting interactive controls', () => {
    render(
      <Button asChild>
        <Link href="/next">Continue</Link>
      </Button>,
    );

    const link = screen.getByRole('link', { name: 'Continue' });
    expect(link.closest('button')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Continue' })).not.toBeInTheDocument();
  });

  it('uses alert-dialog semantics and stays open when confirmation fails', async () => {
    const user = userEvent.setup();
    render(
      <ConfirmButton title="Delete organization" onConfirm={() => Promise.reject(new Error('failed'))}>
        Delete
      </ConfirmButton>,
    );

    await user.click(screen.getByRole('button', { name: 'Delete' }));
    const dialog = screen.getByRole('alertdialog', { name: 'Delete organization' });
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    expect(screen.getByRole('alertdialog', { name: 'Delete organization' })).toBeInTheDocument();
  });
});

describe('playground', () => {
  it('labels playground sessions in recent activity without exposing their ids', async () => {
    const playgroundSessionId = '01941f29-7c00-7000-8000-000000000001';
    server.use(
      http.get(`/api/v1/orgs/${ORG.id}/workspaces/${WORKSPACES[0].slug}/events`, () =>
        HttpResponse.json([
          {
            event_id: '01941f29-7c00-7000-8000-000000000002',
            request_id: '01941f29-7c00-7000-8000-000000000003',
            occurred_at: now,
            org_id: ORG.id,
            workspace_id: WORKSPACES[0].id,
            key_id: playgroundSessionId,
            model_id: 'openai/gpt-test',
            provider_id: 'provider-1',
            bundle_id: '01941f29-7c00-7000-8000-000000000004',
            input_tokens: 12,
            output_tokens: 4,
            cost_usd: 0.001,
            cost_input_usd: 0.0005,
            cost_output_usd: 0.0005,
            cache_read_tokens: 0,
            cache_write_tokens: 0,
            latency_ms: 100,
            status: 'ok',
            stream: true,
            credential_id: null,
            credential_scope: null,
          },
        ]),
      ),
    );
    window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}`);
    render(<App />);

    const activity = await screen.findByRole('row', { name: /openai\/gpt-test Playground/ });

    expect(within(activity).getByText('Playground')).toBeInTheDocument();
    expect(within(activity).queryByText(playgroundSessionId)).not.toBeInTheDocument();
  });

  it('starts a session automatically and streams a response through the inference prefix', async () => {
    const provider = taxonomyProvider('provider-1', 'openai');
    const model = {
      id: 'model-1',
      name: 'openai/gpt-test',
      provider_id: provider.id,
      upstream_model: 'gpt-test',
      input_price_per_mtok: 1,
      output_price_per_mtok: 2,
      cache_read_price_per_mtok: 0,
      cache_write_price_per_mtok: 0,
      context_window: 128000,
      max_output_tokens: 4096,
      capabilities: ['streaming'],
      created_at: now,
      updated_at: now,
      deleted_at: null,
    };
    let dialect = '';
    let requestedWith = '';
    let sessions = 0;
    server.use(
      http.get(`/api/v1/orgs/${ORG.id}/workspaces/${WORKSPACES[0].slug}/taxonomy`, () =>
        HttpResponse.json({ providers: [provider], models: [model] }),
      ),
      http.put(`/api/v1/orgs/${ORG.id}/workspaces/${WORKSPACES[0].slug}/playground-session`, () => {
        sessions += 1;
        return HttpResponse.json({ id: 'session-1', expires_at: '2026-01-01T01:00:00Z', status: 'ready' });
      }),
      http.post('/inf/v1/chat/completions', ({ request }) => {
        dialect = request.headers.get('x-airllm-dialect') ?? '';
        requestedWith = request.headers.get('x-requested-with') ?? '';
        return HttpResponse.text(
          'data: {"choices":[{"delta":{"content":"hello from the gateway"}}]}\n\ndata: {"choices":[{"finish_reason":"stop"}],"usage":{"prompt_tokens":12,"completion_tokens":4,"prompt_tokens_details":{"cached_tokens":2}}}\n\ndata: [DONE]\n\n',
          { headers: { 'content-type': 'text/event-stream' } },
        );
      }),
    );
    window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}/playground`);
    render(<App />);
    const user = userEvent.setup();

    const composer = await screen.findByPlaceholderText('Send a message... (Shift+Enter for newline)');
    await user.type(composer, 'hello');
    await user.click(screen.getByRole('button', { name: 'Send message' }));

    expect(composer).toHaveFocus();

    expect(await screen.findByText('hello from the gateway')).toBeInTheDocument();
    expect(composer).toHaveFocus();
    expect(screen.getByText('12 input')).toBeInTheDocument();
    expect(screen.getByText('4 output')).toBeInTheDocument();
    expect(screen.getByText('16 total')).toBeInTheDocument();
    expect(screen.getByText('2 cached')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Generate playground key' })).not.toBeInTheDocument();
    expect(sessions).toBe(1);
    expect(dialect).toBe('openai_native');
    expect(requestedWith).toBe('fetch');

    const workspaceNavigation = screen.getByRole('navigation', { name: 'Workspace navigation' });
    const workspaceOverview = within(workspaceNavigation)
      .getAllByRole('link', { name: 'Overview' })
      .find((link) => link.getAttribute('href')?.includes('/workspaces/'));
    expect(workspaceOverview).toBeDefined();
    await user.click(workspaceOverview!);
    await user.click(within(workspaceNavigation).getByRole('link', { name: 'Playground' }));
    expect(await screen.findByText('hello from the gateway')).toBeInTheDocument();
    expect(screen.getByText(/Active until/)).toBeInTheDocument();
    expect(sessions).toBe(1);
  });

  it('filters the model selector by model and provider name', async () => {
    const firstProvider = taxonomyProvider('provider-1', 'openai');
    const secondProvider = taxonomyProvider('provider-2', 'anthropic');
    const models = [
      {
        id: 'model-1',
        name: 'openai/gpt-test',
        provider_id: firstProvider.id,
        upstream_model: 'gpt-test',
        input_price_per_mtok: 1,
        output_price_per_mtok: 2,
        cache_read_price_per_mtok: 0,
        cache_write_price_per_mtok: 0,
        context_window: 128000,
        max_output_tokens: 4096,
        capabilities: ['streaming'],
        created_at: now,
        updated_at: now,
        deleted_at: null,
      },
      {
        id: 'model-2',
        name: 'anthropic/claude-test',
        provider_id: secondProvider.id,
        upstream_model: 'claude-test',
        input_price_per_mtok: 1,
        output_price_per_mtok: 2,
        cache_read_price_per_mtok: 0,
        cache_write_price_per_mtok: 0,
        context_window: 128000,
        max_output_tokens: 4096,
        capabilities: ['streaming'],
        created_at: now,
        updated_at: now,
        deleted_at: null,
      },
    ];
    server.use(
      http.get(`/api/v1/orgs/${ORG.id}/workspaces/${WORKSPACES[0].slug}/taxonomy`, () =>
        HttpResponse.json({ providers: [firstProvider, secondProvider], models }),
      ),
    );
    window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}/playground`);
    render(<App />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Model' }));
    const dialog = screen.getByRole('dialog', { name: 'Select model' });
    await user.type(within(dialog).getByPlaceholderText('Search models...'), 'anthropic');
    await user.keyboard('{ArrowDown}{Enter}');

    const modelSelector = screen.getByRole('button', { name: 'Model' });
    expect(modelSelector).toHaveTextContent('anthropic/claude-test');
    expect(screen.getByPlaceholderText('Send a message... (Shift+Enter for newline)')).toHaveFocus();
  });

  it('does not send temperature when the selected model rejects it', async () => {
    const provider = taxonomyProvider('provider-1', 'openai');
    const model = {
      id: 'model-1',
      name: 'openai/gpt-5-nano',
      provider_id: provider.id,
      upstream_model: 'gpt-5-nano',
      input_price_per_mtok: 1,
      output_price_per_mtok: 2,
      cache_read_price_per_mtok: 0,
      cache_write_price_per_mtok: 0,
      context_window: 128000,
      max_output_tokens: 4096,
      capabilities: ['streaming'],
      parameter_support: { temperature: 'unsupported' },
      created_at: now,
      updated_at: now,
      deleted_at: null,
    };
    let requestBody: Record<string, unknown> = {};
    server.use(
      http.get(`/api/v1/orgs/${ORG.id}/workspaces/${WORKSPACES[0].slug}/taxonomy`, () =>
        HttpResponse.json({ providers: [provider], models: [model] }),
      ),
      http.put(`/api/v1/orgs/${ORG.id}/workspaces/${WORKSPACES[0].slug}/playground-session`, () =>
        HttpResponse.json({ id: 'session-1', expires_at: '2026-01-01T01:00:00Z', status: 'ready' }),
      ),
      http.post('/inf/v1/chat/completions', async ({ request }) => {
        requestBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.text(
          'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: {"choices":[{"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
          {
            headers: { 'content-type': 'text/event-stream' },
          },
        );
      }),
    );
    window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}/playground`);
    render(<App />);
    const user = userEvent.setup();

    const temperature = await screen.findByRole('slider', { name: /Temperature/ });
    expect(temperature).toBeDisabled();
    expect(screen.getByText('Not supported by this model')).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText('Send a message... (Shift+Enter for newline)'), 'hello');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    await screen.findByText('ok');

    expect(requestBody).not.toHaveProperty('temperature');
  });
});
