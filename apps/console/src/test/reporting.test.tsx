import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, server } from './msw';

const totals = { requests: 2, input_tokens: 30, output_tokens: 10, cache_read_tokens: 3, cache_write_tokens: 2, cost_usd: '0.000005' };
const period = {
  start_at: '2026-01-01T00:00:00Z',
  end_at: '2026-01-31T00:00:00Z',
  previous_start_at: '2025-12-02T00:00:00Z',
  previous_end_at: '2026-01-01T00:00:00Z',
  timezone: 'UTC',
};
const requestSummary = {
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
};

function renderAt(path: string) {
  window.localStorage.setItem('airmux_org_id', ORG.id);
  window.history.replaceState(null, '', path);
  return render(<App />);
}

it('opens organization reporting and drills a model into filtered requests', async () => {
  server.use(
    http.get('/api/v1/organizations/:orgId/reports/usage', () =>
      HttpResponse.json({
        data: {
          totals,
          comparison: { ...totals, requests: 1, input_tokens: 10, output_tokens: 5, cost_usd: '0' },
          period,
          daily: [{ date: period.start_at, ...totals }],
          updated_at: period.end_at,
        },
      }),
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
          requests: [requestSummary],
          next_offset: null,
        },
      }),
    ),
  );

  const user = userEvent.setup();
  renderAt('/org');

  expect(await screen.findByRole('heading', { name: 'Usage' })).toBeInTheDocument();
  const spendCard = (await screen.findByText('Spend', { selector: 'div' })).closest('.p-4');
  expect(spendCard?.querySelector('svg')).not.toHaveClass('mt-1');
  expect(within(spendCard as HTMLElement).getByText('+$0.000005')).toBeInTheDocument();
  const requestsCard = screen.getByText('Requests', { selector: 'div' }).closest('.p-4') as HTMLElement;
  expect(within(requestsCard).getByText('+1')).toBeInTheDocument();
  expect(screen.queryAllByText(/vs previous period/)).toHaveLength(0);
  const tokensCard = screen.getByText('Tokens', { selector: 'div' }).closest('.p-4') as HTMLElement;
  expect(within(tokensCard).getByText('40')).toBeInTheDocument();
  expect(within(tokensCard).getByText('+25')).toBeInTheDocument();
  expect(within(tokensCard).getByText('Input')).toBeInTheDocument();
  expect(within(tokensCard).getByText('Output')).toBeInTheDocument();
  expect(within(tokensCard).getByText('Cache read')).toBeInTheDocument();
  expect(within(tokensCard).getByText('Cache write')).toBeInTheDocument();
  expect(within(tokensCard).getByText('3')).toBeInTheDocument();
  expect(within(tokensCard).getByText('2')).toBeInTheDocument();
  const spendAxis = screen.getByRole('group', { name: 'Spend axis' });
  expect(within(spendAxis).getByText('$0.000005')).toBeInTheDocument();
  expect(within(spendAxis).getByText('$0')).toBeInTheDocument();
  expect(spendAxis.parentElement?.lastElementChild).toHaveClass('w-20', 'shrink-0');
  expect(screen.queryByText(/estimated gateway usage/i)).not.toBeInTheDocument();
  expect(window.location.pathname).toBe('/org');
  expect(screen.getByRole('combobox', { name: 'Group by' })).toHaveClass('w-48', 'shrink-0');
  await user.click(await screen.findByRole('combobox', { name: 'Group by' }));
  await user.click(screen.getByRole('option', { name: 'Model' }));
  const attribution = await screen.findByRole('table', { name: 'Attribution' });
  expect(within(attribution).getByText('Cost per request')).toBeInTheDocument();
  expect(within(attribution).getByText('Input · Output')).toBeInTheDocument();
  expect(within(attribution).getByText('30 · 10')).toBeInTheDocument();
  const modelLink = within(attribution).getByRole('link', { name: 'model-a' });
  expect(modelLink).toHaveClass('text-primary', 'hover:underline');
  expect(modelLink.closest('td')).not.toHaveClass('[&_a]:text-primary');
  expect(within(modelLink).getByText('model-a').parentElement).toHaveClass('rounded', 'border');
  await user.click(modelLink);

  expect(await screen.findByRole('heading', { name: 'Requests' })).toBeInTheDocument();
  expect(window.location.pathname).toBe('/org/requests');
  expect(new URLSearchParams(window.location.search).get('model_id')).toBe('model-a');
  const requestLink = await screen.findByRole('link', { name: 'request-1' });
  const requestsTable = screen.getByRole('table', { name: 'Requests' });
  expect(within(requestsTable).getByText('Inference Key')).toBeInTheDocument();
  expect(within(requestsTable).queryByText('Inference Key · Source')).not.toBeInTheDocument();
  expect(within(requestsTable).getByText('Input · Output')).toBeInTheDocument();
  expect(within(requestsTable).getByText('30 · 10')).toBeInTheDocument();
  expect(requestLink).toHaveClass('text-primary', 'hover:underline');
  expect(within(screen.getByRole('table', { name: 'Requests' })).getByText('model-a').parentElement).toHaveClass('rounded', 'border');
});

it('opens a listed request without carrying its old page offset', async () => {
  server.use(
    http.get('/api/v1/organizations/:orgId/reports/requests', () => HttpResponse.json({ data: { requests: [requestSummary], next_offset: null } })),
  );

  renderAt('/org/requests?offset=20');

  const requestLink = await screen.findByRole('link', { name: 'request-1' });
  expect(requestLink).not.toHaveAttribute('href', expect.stringContaining('offset='));
});

it('shows zero instead of NaN when cache token counts are absent', async () => {
  server.use(
    http.get('/api/v1/organizations/:orgId/reports/usage', () =>
      HttpResponse.json({
        data: {
          totals: { ...totals, cache_read_tokens: undefined, cache_write_tokens: undefined },
          comparison: totals,
          period,
          daily: [],
          updated_at: period.end_at,
        },
      }),
    ),
  );

  renderAt('/org');

  const tokensCard = (await screen.findByText('Tokens', { selector: 'div' })).closest('.p-4') as HTMLElement;
  expect(within(tokensCard).getAllByText('0')).toHaveLength(2);
  expect(within(tokensCard).queryByText('NaN')).not.toBeInTheDocument();
});

it('keeps workspace request rows compact with the full request ID available', async () => {
  server.use(
    http.get('/api/v1/organizations/:orgId/reports/requests', () =>
      HttpResponse.json({
        data: {
          requests: [{ ...requestSummary, request_id: '01a0cbde-afee-7867-a902-e70b75b471ba', model_id: 'anthropic/claude-opus-4-5-20251101' }],
          next_offset: null,
        },
      }),
    ),
  );

  renderAt(`/org/workspaces/${WORKSPACES[0].slug}/requests`);

  const table = await screen.findByRole('table', { name: 'Requests' });
  expect(within(table).queryByRole('columnheader', { name: 'Workspace' })).not.toBeInTheDocument();
  expect(within(table).getByRole('link', { name: '01a0cbde-afee-7867-a902-e70b75b471ba' })).toHaveAttribute(
    'title',
    '01a0cbde-afee-7867-a902-e70b75b471ba',
  );
  const model = within(table).getByText('anthropic/claude-opus-4-5-20251101');
  expect(model).toHaveClass('truncate');
  expect(model.parentElement).toHaveClass('justify-start', 'max-w-48');
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
  expect((await screen.findAllByText('$0.000005')).length).toBeGreaterThan(0);
  expect(screen.queryAllByText(/vs previous period/)).toHaveLength(0);
  expect(
    screen.queryByText('A request can appear in several model or provider groups when it retries. Spending is counted once per attempt.'),
  ).not.toBeInTheDocument();
});

it.each([
  ['/org', '/api/v1/organizations/:orgId/reports/usage'],
  ['/org/requests', '/api/v1/organizations/:orgId/reports/requests'],
])('spins the refresh icon while %s reloads', async (path, endpoint) => {
  const user = userEvent.setup();
  renderAt(path);

  const refresh = await screen.findByRole('button', { name: 'Refresh' });
  if (path === '/org') await screen.findAllByText('No usage in this period.');
  else await screen.findByText('No requests match these filters.');
  expect(screen.queryByText(/Events arrive asynchronously/)).not.toBeInTheDocument();
  server.use(
    http.get(endpoint, async () => {
      await delay(300);
      return HttpResponse.json({
        data: path === '/org' ? { totals, comparison: totals, period, daily: [], updated_at: period.end_at } : { requests: [], next_offset: null },
      });
    }),
  );

  await user.click(refresh);
  expect(refresh.querySelector('svg')).toHaveClass('motion-safe:animate-spin');
  await waitFor(() => expect(refresh.querySelector('svg')).not.toHaveClass('motion-safe:animate-spin'));
});

it('polls requests in Live mode and briefly highlights new rows', async () => {
  const user = userEvent.setup();
  renderAt('/org/requests');

  await screen.findByText('No requests match these filters.');
  expect(screen.getByRole('button', { name: 'Live' }).querySelector('span')).toHaveClass('bg-muted-foreground');
  await user.click(screen.getByRole('button', { name: 'Live' }));
  expect(screen.getByRole('button', { name: 'Live' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByRole('button', { name: 'Live' }).querySelector('span')).toHaveClass('bg-success');
  server.use(
    http.get('/api/v1/organizations/:orgId/reports/requests', () => HttpResponse.json({ data: { requests: [requestSummary], next_offset: null } })),
  );

  const requestLink = await screen.findByRole('link', { name: 'request-1' }, { timeout: 5_000 });
  expect(requestLink.closest('tr')).toHaveClass('motion-safe:animate-request-arrival');
});

it('shows the full attempt history while identifying the filtered provider contribution', async () => {
  server.use(
    http.get('/api/v1/organizations/:orgId/reports/filter-options', ({ request }) => {
      const dimension = new URL(request.url).searchParams.get('dimension');
      const items = {
        owner: [{ id: 'user-a', name: 'owner@example.com' }],
        key: [{ id: 'key-a', name: 'Checkout' }],
        credential: [
          { id: 'credential-a', name: 'Primary credential' },
          { id: 'credential-b', name: 'Backup credential' },
        ],
      };
      return HttpResponse.json({ data: { items: items[dimension as keyof typeof items] ?? [] } });
    }),
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
          within_period: false,
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
  expect(await within(panel).findByText('This request started outside the selected period.')).toBeInTheDocument();
  expect(await within(panel).findByText('provider-a', { exact: false })).toBeInTheDocument();
  expect(within(panel).getByText('provider-b', { exact: false })).toBeInTheDocument();
  expect(within(panel).getAllByText('Provider')).toHaveLength(2);
  expect(within(panel).getAllByText('Model')).toHaveLength(2);
  expect(within(panel).getByText('Matches filters')).toBeInTheDocument();
  expect(within(panel).getByText('Outside filters')).toBeInTheDocument();
  expect(within(panel).getByText('$0.000005')).toBeInTheDocument();
  expect(within(panel).getByText('owner@example.com')).toBeInTheDocument();
  expect(within(panel).getByText('User')).toBeInTheDocument();
  expect(within(panel).getAllByText('Success').length).toBeGreaterThan(0);
  expect(within(panel).getByText('Upstream error')).toBeInTheDocument();
  expect(within(panel).getByText('Gateway-derived')).toBeInTheDocument();
  expect(within(panel).queryByText(/estimated/i)).not.toBeInTheDocument();
  expect(within(panel).getByText('Checkout')).toBeInTheDocument();
  expect(within(panel).getByText('Primary credential')).toBeInTheDocument();
  expect(within(panel).getByText('Backup credential')).toBeInTheDocument();
  expect(within(panel).getByText('Input · Output tokens')).toBeInTheDocument();
  expect(within(panel).getAllByText('Input · Output')).toHaveLength(2);
  expect(within(panel).getAllByText('Cache Read · Write')).toHaveLength(2);
  expect(within(panel).getAllByText('Input · Output cost')).toHaveLength(2);
  expect(within(panel).getAllByText('model-a')[0].parentElement).toHaveClass('font-mono');
  const attempts = within(panel).getByRole('heading', { name: 'Provider attempts' }).parentElement as HTMLElement;
  for (const details of attempts.querySelectorAll('dl')) expect(details).toHaveClass('text-sm');
  expect(attempts.querySelector('span.font-mono')).toHaveClass('text-sm');
  expect(panel).toHaveClass('p-6');
});

it('uses a themed calendar to update the report date', async () => {
  const user = userEvent.setup();
  renderAt('/org?period=custom&start_date=2026-01-01&end_date=2026-01-31');

  await user.click(await screen.findByRole('button', { name: 'Choose start date, January 1, 2026' }));
  const calendar = screen.getByRole('dialog', { name: 'Start date' });
  expect(calendar).toHaveClass('bg-card', 'text-card-foreground');
  await user.click(within(calendar).getByRole('button', { name: 'January 2, 2026' }));

  expect(new URLSearchParams(window.location.search).get('start_date')).toBe('2026-01-02');
});

it('shows a denied playground request without a fake provider attempt or inference key', async () => {
  server.use(
    http.get('/api/v1/organizations/:orgId/reports/requests/:requestId', () =>
      HttpResponse.json({
        data: {
          ...requestSummary,
          status: 'denied',
          request_source: 'playground',
          attempt_count: 0,
          within_period: true,
          attempts: [
            {
              event_id: 'event-denied',
              attempt_started_at: null,
              occurred_at: period.start_at,
              model_id: 'model-a',
              provider_id: '',
              credential_id: null,
              status: 'denied',
              input_tokens: 0,
              output_tokens: 0,
              cache_read_tokens: 0,
              cache_write_tokens: 0,
              cost_usd: '0',
              cost_input_usd: '0',
              cost_output_usd: '0',
              token_usage_source: 'not_applicable',
              latency_ms: 0,
              matches_filter: false,
            },
          ],
        },
      }),
    ),
  );

  renderAt('/org/requests?request_id=request-1');

  const panel = await screen.findByRole('dialog', { name: 'Request details' });
  expect(await within(panel).findByText('Denied')).toBeInTheDocument();
  expect(within(panel).getByText('User')).toBeInTheDocument();
  expect(within(panel).queryByText('Inference key')).not.toBeInTheDocument();
  expect(within(panel).queryByText('Provider attempts')).not.toBeInTheDocument();
  expect(within(panel).queryByText('N/A')).not.toBeInTheDocument();
});
