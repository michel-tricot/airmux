import type * as Api from '@workspace/api-client-react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, paged, server } from './msw';
import { now, taxonomyProvider } from './fixtures';
beforeEach(() => window.localStorage.setItem('airmux_org_id', ORG.id));
describe('playground', () => {
  it('labels playground sessions in recent activity without exposing their ids', async () => {
    const playgroundSessionId = '01941f29-7c00-7000-8000-000000000001';
    server.use(
      http.get(`/api/v1/organizations/${ORG.id}/workspaces/${WORKSPACES[0].slug}/events`, () =>
        paged<Api.UsageEventOut>([
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
            max_output_tokens: 128,
            cost_usd: '0.001',
            cost_input_usd: '0.0005',
            cost_output_usd: '0.0005',
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
      egress_kind: null,
      input_modalities: ['text'],
      output_modalities: ['text'],
      parameter_support: {},
      id: 'model-1',
      name: 'openai/gpt-test',
      provider_id: provider.id,
      upstream_model: 'gpt-test',
      input_price_per_mtok: '1',
      output_price_per_mtok: '2',
      cache_read_price_per_mtok: '0',
      cache_write_price_per_mtok: '0',
      context_window: 128000,
      max_output_tokens: 4096,
      capabilities: ['streaming'],
      created_at: now,
      updated_at: now,
      deleted_at: null,
    } satisfies Api.ModelOut;
    let requestedWith = '';
    let requestBody: Record<string, unknown> = {};
    let sessions = 0;
    server.use(
      http.get(`/api/v1/organizations/${ORG.id}/workspaces/${WORKSPACES[0].slug}/taxonomy`, () =>
        HttpResponse.json<{ data: Api.TaxonomyOut }>({ data: { providers: [provider], models: [model] } }),
      ),
      http.put(`/api/v1/organizations/${ORG.id}/workspaces/${WORKSPACES[0].slug}/playground-session`, () => {
        sessions += 1;
        return HttpResponse.json<{ data: Api.PlaygroundSessionReadyOut }>({
          data: { id: 'session-1', expires_at: '2026-01-01T01:00:00Z', status: 'ready' },
        });
      }),
      http.post('/inf/v1/chat/completions', async ({ request }) => {
        requestedWith = request.headers.get('x-requested-with') ?? '';
        requestBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.text(
          [
            'data: {"id":"reply","object":"chat.completion.chunk","created":1,"model":"model-1","choices":[{"index":0,"delta":{"content":"hello from the gateway"}}]}',
            '',
            'data: {"id":"reply","object":"chat.completion.chunk","created":1,"model":"model-1","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}',
            '',
            'data: {"id":"reply","object":"chat.completion.chunk","created":1,"model":"model-1","choices":[],"usage":{"prompt_tokens":12,"completion_tokens":4,"total_tokens":16,"prompt_tokens_details":{"cached_tokens":2}},"gateway":{"adjustments":[]}}',
            '',
            'data: [DONE]',
            '',
          ].join('\n'),
          { headers: { 'content-type': 'text/event-stream' } },
        );
      }),
    );
    window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}/playground`);
    render(<App />);
    const user = userEvent.setup();

    const composer = await screen.findByPlaceholderText('Send a message... (Shift+Enter for newline)');
    expect(document.querySelector('[data-playground-scroll-anchor]')).not.toBeInTheDocument();
    const maxTokens = screen.getByLabelText('Max tokens');
    await user.click(screen.getByRole('button', { name: 'Increase Max tokens' }));
    expect(maxTokens).toHaveValue(1);
    await user.click(screen.getByRole('button', { name: 'Decrease Max tokens' }));
    expect(maxTokens).toHaveValue(1);
    await user.clear(maxTokens);
    await user.type(composer, 'hello');
    await user.click(screen.getByRole('button', { name: 'Send message' }));

    expect(composer).toHaveFocus();

    expect(await screen.findByText('hello from the gateway')).toBeInTheDocument();
    expect(document.querySelector('[data-playground-scroll-anchor]')).toBeInTheDocument();
    expect(composer).toHaveFocus();
    expect(screen.getByText('16 total')).toBeInTheDocument();
    expect(screen.queryByText('12 input')).not.toBeInTheDocument();
    expect(screen.queryByText('2 cached')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Show response details' }));
    expect(screen.getByText('12 input')).toBeInTheDocument();
    expect(screen.getByText('4 output')).toBeInTheDocument();
    expect(screen.getByText('2 cached')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'View cURL' }));
    const curlDialog = screen.getByRole('dialog', { name: 'Replicate request' });
    expect(curlDialog).toHaveTextContent('/inf/v1/chat/completions');
    expect(curlDialog).toHaveTextContent('Authorization: Bearer $AIRMUX_INFERENCE_KEY');
    expect(curlDialog).toHaveTextContent('openai/gpt-test');
    expect(curlDialog).toHaveTextContent('"content": "hello"');
    expect(curlDialog).toHaveTextContent('"temperature": 1');
    expect(curlDialog).toHaveTextContent('"stream": true');
    const copyCurl = within(curlDialog).getByRole('button', { name: 'Copy cURL' });
    await user.click(copyCurl);
    expect(await navigator.clipboard.readText()).toContain('/inf/v1/chat/completions');
    expect(await within(curlDialog).findByRole('button', { name: 'Copied cURL' })).toBeInTheDocument();
    await user.click(within(curlDialog).getByRole('button', { name: 'Close' }));
    expect(sessions).toBe(1);
    expect(requestedWith).toBe('fetch');
    expect(requestBody.messages).toEqual([{ role: 'user', content: 'hello' }]);

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

  it('explains when a response is stopped by content filtering', async () => {
    const provider = taxonomyProvider('provider-1', 'anthropic');
    const model = {
      egress_kind: null,
      parameter_support: {},
      id: 'model-1',
      name: 'anthropic/claude-test',
      provider_id: provider.id,
      upstream_model: 'claude-test',
      input_price_per_mtok: '1',
      output_price_per_mtok: '2',
      cache_read_price_per_mtok: '0',
      cache_write_price_per_mtok: '0',
      context_window: 128000,
      max_output_tokens: 4096,
      input_modalities: ['text'],
      output_modalities: ['text'],
      capabilities: ['streaming'],
      created_at: now,
      updated_at: now,
      deleted_at: null,
    } satisfies Api.ModelOut;
    server.use(
      http.get(`/api/v1/organizations/${ORG.id}/workspaces/${WORKSPACES[0].slug}/taxonomy`, () =>
        HttpResponse.json<{ data: Api.TaxonomyOut }>({ data: { providers: [provider], models: [model] } }),
      ),
      http.put(`/api/v1/organizations/${ORG.id}/workspaces/${WORKSPACES[0].slug}/playground-session`, () =>
        HttpResponse.json<{ data: Api.PlaygroundSessionReadyOut }>({
          data: { id: 'session-1', expires_at: '2026-01-01T01:00:00Z', status: 'ready' },
        }),
      ),
      http.post('/inf/v1/chat/completions', () =>
        HttpResponse.text(
          'data: {"id":"reply","object":"chat.completion.chunk","created":1,"model":"model-1","choices":[{"index":0,"delta":{},"finish_reason":"content_filter"}]}\n\ndata: {"id":"reply","object":"chat.completion.chunk","created":1,"model":"model-1","choices":[],"usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0,"prompt_tokens_details":{"cached_tokens":0}},"gateway":{"adjustments":[]}}\n\ndata: [DONE]\n\n',
          {
            headers: { 'content-type': 'text/event-stream' },
          },
        ),
      ),
    );
    window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}/playground`);
    render(<App />);
    const user = userEvent.setup();

    await user.type(await screen.findByPlaceholderText('Send a message... (Shift+Enter for newline)'), 'hello');
    await user.click(screen.getByRole('button', { name: 'Send message' }));

    expect(await screen.findByText('Response stopped: content_filter')).toBeInTheDocument();
    expect(screen.queryByText('No text content returned')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'View cURL' })).toBeInTheDocument();
  });

  it('filters the model selector by model and provider name', async () => {
    const firstProvider = taxonomyProvider('provider-1', 'openai');
    const secondProvider = taxonomyProvider('provider-2', 'anthropic');
    const models = [
      {
        egress_kind: null,
        input_modalities: ['text'],
        output_modalities: ['text'],
        parameter_support: {},
        id: 'model-1',
        name: 'openai/gpt-test',
        provider_id: firstProvider.id,
        upstream_model: 'gpt-test',
        input_price_per_mtok: '1',
        output_price_per_mtok: '2',
        cache_read_price_per_mtok: '0',
        cache_write_price_per_mtok: '0',
        context_window: 128000,
        max_output_tokens: 4096,
        capabilities: ['streaming'],
        created_at: now,
        updated_at: now,
        deleted_at: null,
      } satisfies Api.ModelOut,
      {
        egress_kind: null,
        input_modalities: ['text'],
        output_modalities: ['text'],
        parameter_support: {},
        id: 'model-2',
        name: 'anthropic/claude-test',
        provider_id: secondProvider.id,
        upstream_model: 'claude-test',
        input_price_per_mtok: '1',
        output_price_per_mtok: '2',
        cache_read_price_per_mtok: '0',
        cache_write_price_per_mtok: '0',
        context_window: 128000,
        max_output_tokens: 4096,
        capabilities: ['streaming'],
        created_at: now,
        updated_at: now,
        deleted_at: null,
      } satisfies Api.ModelOut,
    ];
    server.use(
      http.get(`/api/v1/organizations/${ORG.id}/workspaces/${WORKSPACES[0].slug}/taxonomy`, () =>
        HttpResponse.json<{ data: Api.TaxonomyOut }>({ data: { providers: [firstProvider, secondProvider], models } }),
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
      egress_kind: null,
      input_modalities: ['text'],
      output_modalities: ['text'],
      id: 'model-1',
      name: 'openai/gpt-5-nano',
      provider_id: provider.id,
      upstream_model: 'gpt-5-nano',
      input_price_per_mtok: '1',
      output_price_per_mtok: '2',
      cache_read_price_per_mtok: '0',
      cache_write_price_per_mtok: '0',
      context_window: 128000,
      max_output_tokens: 4096,
      capabilities: ['streaming'],
      parameter_support: { temperature: 'unsupported' },
      created_at: now,
      updated_at: now,
      deleted_at: null,
    } satisfies Api.ModelOut;
    let requestBody: Record<string, unknown> = {};
    server.use(
      http.get(`/api/v1/organizations/${ORG.id}/workspaces/${WORKSPACES[0].slug}/taxonomy`, () =>
        HttpResponse.json<{ data: Api.TaxonomyOut }>({ data: { providers: [provider], models: [model] } }),
      ),
      http.put(`/api/v1/organizations/${ORG.id}/workspaces/${WORKSPACES[0].slug}/playground-session`, () =>
        HttpResponse.json<{ data: Api.PlaygroundSessionReadyOut }>({
          data: { id: 'session-1', expires_at: '2026-01-01T01:00:00Z', status: 'ready' },
        }),
      ),
      http.post('/inf/v1/chat/completions', async ({ request }) => {
        requestBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.text(
          'data: {"id":"reply","object":"chat.completion.chunk","created":1,"model":"model-1","choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: {"id":"reply","object":"chat.completion.chunk","created":1,"model":"model-1","choices":[],"usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0,"prompt_tokens_details":{"cached_tokens":0}},"gateway":{"adjustments":[]}}\n\ndata: [DONE]\n\n',
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
