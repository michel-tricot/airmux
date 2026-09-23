import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, server } from './msw';

const totals = { requests: 2, input_tokens: 30, output_tokens: 10, cost_usd: '0.000005' };
const period = {
  start_at: '2026-01-01T00:00:00Z',
  end_at: '2026-01-31T00:00:00Z',
  previous_start_at: '2025-12-02T00:00:00Z',
  previous_end_at: '2026-01-01T00:00:00Z',
  timezone: 'UTC',
};

function renderAt(path: string) {
  window.localStorage.setItem('airmux_org_id', ORG.id);
  window.history.replaceState(null, '', path);
  return render(<App />);
}

it('opens organization reporting and drills a model into filtered requests', async () => {
  server.use(
    http.get('/api/v1/organizations/:orgId/reports/usage', () =>
      HttpResponse.json({ data: { totals, comparison: totals, period, daily: [{ date: period.start_at, ...totals }], updated_at: period.end_at } }),
    ),
    http.get('/api/v1/organizations/:orgId/reports/attribution', () =>
      HttpResponse.json({
        data: {
          items: [{ id: 'model-a', name: 'model-a', ...totals, previous_cost_usd: '0' }],
          next_offset: null,
        },
      }),
    ),
    http.get('/api/v1/organizations/:orgId/reports/requests', () =>
      HttpResponse.json({
        data: {
          requests: [
            {
              request_id: 'request-1',
              started_at: period.start_at,
              status: 'ok',
              requested_model_id: 'model-a',
              model_id: 'model-a',
              provider_id: 'provider-a',
              workspace_id: WORKSPACES[0].id,
              key_id: 'key-a',
              user_id: 'user-a',
              request_source: 'inference_key',
              attempt_count: 1,
              input_tokens: 30,
              output_tokens: 10,
              cost_usd: '0.000005',
            },
          ],
          next_offset: null,
        },
      }),
    ),
  );

  const user = userEvent.setup();
  renderAt('/org');

  expect(await screen.findByRole('heading', { name: 'Usage' })).toBeInTheDocument();
  expect(window.location.pathname).toBe('/org');
  await user.click(await screen.findByRole('combobox', { name: 'Group by' }));
  await user.click(screen.getByRole('option', { name: 'Model' }));
  const attribution = await screen.findByRole('table', { name: 'Attribution' });
  await user.click(within(attribution).getByRole('link', { name: 'model-a' }));

  expect(await screen.findByRole('heading', { name: 'Requests' })).toBeInTheDocument();
  expect(window.location.pathname).toBe('/org/requests');
  expect(new URLSearchParams(window.location.search).get('model_id')).toBe('model-a');
  expect(await screen.findByText('request-1')).toBeInTheDocument();
});

it('uses the same report endpoint with a workspace ID for workspace reporting', async () => {
  server.use(
    http.get('/api/v1/organizations/:orgId/reports/usage', ({ request }) => {
      const workspaceId = new URL(request.url).searchParams.get('workspace_id');
      return HttpResponse.json({
        data: {
          totals: workspaceId === WORKSPACES[0].id ? totals : { ...totals, cost_usd: '0' },
          comparison: totals,
          period,
          daily: [{ date: period.start_at, ...totals }],
          updated_at: period.end_at,
        },
      });
    }),
    http.get('/api/v1/organizations/:orgId/reports/attribution', () => HttpResponse.json({ data: { items: [], next_offset: null } })),
  );

  renderAt(`/org/workspaces/${WORKSPACES[0].slug}`);

  expect(await screen.findByRole('heading', { name: WORKSPACES[0].name })).toBeInTheDocument();
  expect(await screen.findByText('$0.000005')).toBeInTheDocument();
});

it('shows the full attempt history while identifying the filtered provider contribution', async () => {
  server.use(
    http.get('/api/v1/organizations/:orgId/reports/requests/:requestId', () =>
      HttpResponse.json({
        data: {
          request_id: 'request-1',
          started_at: period.start_at,
          status: 'ok',
          requested_model_id: 'model-a',
          model_id: 'model-b',
          provider_id: 'provider-b',
          workspace_id: WORKSPACES[0].id,
          key_id: 'key-a',
          user_id: 'user-a',
          request_source: 'inference_key',
          attempt_count: 2,
          input_tokens: 30,
          output_tokens: 10,
          cost_usd: '0.000005',
          attempts: [
            {
              event_id: 'event-a',
              attempt_started_at: period.start_at,
              occurred_at: period.start_at,
              model_id: 'model-a',
              provider_id: 'provider-a',
              credential_id: 'credential-a',
              status: 'upstream_error',
              input_tokens: 10,
              output_tokens: 0,
              cache_read_tokens: 0,
              cache_write_tokens: 0,
              cost_usd: '0.000002',
              cost_input_usd: '0.000002',
              cost_output_usd: '0',
              token_usage_source: 'provider',
              latency_ms: 100,
              matches_filter: false,
            },
            {
              event_id: 'event-b',
              attempt_started_at: period.start_at,
              occurred_at: period.start_at,
              model_id: 'model-b',
              provider_id: 'provider-b',
              credential_id: 'credential-b',
              status: 'ok',
              input_tokens: 20,
              output_tokens: 10,
              cache_read_tokens: 3,
              cache_write_tokens: 0,
              cost_usd: '0.000003',
              cost_input_usd: '0.000001',
              cost_output_usd: '0.000002',
              token_usage_source: 'estimated',
              latency_ms: 200,
              matches_filter: true,
            },
          ],
        },
      }),
    ),
    http.get('/api/v1/organizations/:orgId/reports/requests', () => HttpResponse.json({ data: { requests: [], next_offset: null } })),
  );

  renderAt('/org/requests?request_id=request-1&provider_id=provider-b');

  const panel = await screen.findByRole('dialog', { name: 'Request details' });
  expect(await within(panel).findByText('provider-a', { exact: false })).toBeInTheDocument();
  expect(within(panel).getByText('provider-b', { exact: false })).toBeInTheDocument();
  expect(within(panel).getByText('Matches filters')).toBeInTheDocument();
  expect(within(panel).getByText('Outside filters')).toBeInTheDocument();
  expect(within(panel).getByText('$0.000005')).toBeInTheDocument();
});
