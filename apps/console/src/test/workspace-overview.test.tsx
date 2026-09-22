import type * as Api from '@workspace/api-client-react';
import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, server } from './msw';

const attempt: Api.UsageEventOut = {
  event_id: 'event-1',
  request_id: 'request-1',
  request_started_at: '2026-01-01T00:00:00Z',
  attempt_started_at: '2026-01-01T00:00:00Z',
  occurred_at: '2026-01-01T00:00:00Z',
  org_id: ORG.id,
  workspace_id: WORKSPACES[0].id,
  key_id: 'key-1',
  authentication_source: 'inference_key',
  authentication_label: 'Production',
  user_id: '00000000-0000-0000-0000-000000000001',
  principal_label: 'Checkout service',
  principal_type: 'service_account',
  workspace_label: WORKSPACES[0].name,
  requested_model_id: 'primary-model',
  requested_capabilities: [],
  model_id: 'primary-model',
  provider_id: 'provider-1',
  bundle_id: 'bundle-1',
  input_tokens: 2,
  output_tokens: 3,
  token_usage_source: 'provider',
  attempt_index: 1,
  max_output_tokens: null,
  input_price_per_mtok: '1',
  output_price_per_mtok: '2',
  cache_read_price_per_mtok: '0',
  cache_write_price_per_mtok: '0',
  cost_source: 'catalog_estimate',
  cost_usd: '0.1',
  cost_input_usd: '0.04',
  cost_output_usd: '0.06',
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  latency_ms: 10,
  status: 'ok',
  stream: false,
  credential_id: '00000000-0000-0000-0000-000000000002',
  credential_scope: 'workspace',
  credential_name: 'default',
};

it('labels a multi-attempt request and per-model totals as attempts within the event window', async () => {
  server.use(
    http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/events', () =>
      HttpResponse.json({
        data: [
          { ...attempt, event_id: 'event-3', model_id: 'fallback-model', attempt_index: 3 },
          { ...attempt, event_id: 'event-2', status: 'upstream_error', attempt_index: 2 },
          { ...attempt, status: 'upstream_error' },
        ],
        page: { next_cursor: null },
      }),
    ),
  );
  window.localStorage.setItem('airmux_org_id', ORG.id);
  window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}`);
  render(<App />);

  const modelTable = (await screen.findByRole('columnheader', { name: 'Attempts' })).closest('table')!;
  expect(within(modelTable).getByRole('row', { name: 'primary-model 2 10 $0.2000' })).toBeInTheDocument();
  expect(within(modelTable).getByRole('row', { name: 'fallback-model 1 5 $0.1000' })).toBeInTheDocument();
  const attempts = screen.getByText('Attempts', { selector: 'div' }).parentElement!;
  expect(within(attempts).getByText('3')).toBeInTheDocument();
  expect(screen.getAllByText(/latest 200 attempt events/)).toHaveLength(4);
  expect(screen.getByText(/Fallback attempts share one caller request ID/)).toBeInTheDocument();
  expect(screen.getByText(/The window may include only some attempts from a request/)).toBeInTheDocument();
  expect(screen.queryByText('Requests')).not.toBeInTheDocument();
  expect(within(screen.getByText('Input Tokens').parentElement!).getByText('6')).toBeInTheDocument();
  expect(within(screen.getByText('Output Tokens').parentElement!).getByText('9')).toBeInTheDocument();
  expect(within(screen.getByText('Est. cost', { selector: 'div' }).parentElement!).getByText('$0.3000')).toBeInTheDocument();
});

it('limits totals to 200 attempt events even when a request crosses the window boundary', async () => {
  const events = Array.from({ length: 201 }, (_, index) => ({
    ...attempt,
    event_id: `event-${index}`,
    request_id: index === 0 || index === 200 ? 'boundary-request' : `request-${index}`,
  }));
  server.use(
    http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/events', ({ request }) => {
      const params = new URL(request.url).searchParams;
      const offset = params.has('cursor') ? 200 : 0;
      return HttpResponse.json({
        data: events.slice(offset, offset + Number(params.get('limit') ?? 50)),
        page: { next_cursor: offset ? null : 'older-attempt' },
      });
    }),
  );
  window.localStorage.setItem('airmux_org_id', ORG.id);
  window.history.replaceState(null, '', `/org/workspaces/${WORKSPACES[0].slug}`);
  render(<App />);

  const modelTable = (await screen.findByRole('columnheader', { name: 'Attempts' })).closest('table')!;
  expect(within(modelTable).getByRole('row', { name: 'primary-model 200 1.0k $20.00' })).toBeInTheDocument();
  expect(within(screen.getByText('Attempts', { selector: 'div' }).parentElement!).getByText('200')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /load more/i })).not.toBeInTheDocument();
});
