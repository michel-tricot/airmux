import { Permission, type GatewayRequestPageOut, type GatewayRequestReportOut } from '@workspace/api-client-react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, server } from './msw';

const freshness = { as_of: 'snapshot-requests-1', watermark: 'watermark-requests-1', received_at: '2026-09-22T16:00:00Z' };
const period = { start_at: '2026-09-15T16:00:00Z', end_at: '2026-09-22T16:00:00Z', timezone: 'UTC' };

function request(overrides: Partial<GatewayRequestReportOut> = {}): GatewayRequestReportOut {
  return {
    request_id: 'request-1',
    request_started_at: '2026-09-22T15:59:00Z',
    org_id: ORG.id,
    workspace_id: WORKSPACES[0].id,
    workspace_label: WORKSPACES[0].name,
    key_id: 'key-1',
    authentication_source: 'inference_key',
    authentication_label: 'Production key',
    user_id: 'user-1',
    principal_label: 'Dev',
    principal_type: 'human',
    requested_model_id: 'requested-model',
    requested_capabilities: ['tools'],
    bundle_id: 'bundle-1',
    stream: true,
    terminal: {
      event_id: 'terminal-1',
      occurred_at: '2026-09-22T16:00:00Z',
      outcome: 'succeeded',
      expected_attempts: 2,
      latency_ms: 1200,
    },
    attempts: [
      {
        event_id: 'attempt-2',
        attempt_index: 2,
        attempt_started_at: '2026-09-22T15:59:01Z',
        occurred_at: '2026-09-22T16:00:00Z',
        model_id: 'served-final',
        provider_id: 'provider-final',
        max_output_tokens: 100,
        input_price_per_mtok: '1.000001',
        output_price_per_mtok: '2.000002',
        cache_read_price_per_mtok: '0.100001',
        cache_write_price_per_mtok: '0.200002',
        latency_ms: 900,
        status: 'ok',
        credential_id: 'credential-2',
        credential_scope: 'workspace',
        credential_name: 'Workspace credential',
        token_usage_source: 'provider',
        input_tokens: 19,
        output_tokens: 7,
        cache_read_tokens: 5,
        cache_write_tokens: 3,
        cost_source: 'catalog_estimate',
        cost_usd: '0.000000000444',
        cost_input_usd: '0.000000000111',
        cost_output_usd: '0.000000000333',
      },
      {
        event_id: 'attempt-1',
        attempt_index: 1,
        attempt_started_at: '2026-09-22T15:59:00Z',
        occurred_at: '2026-09-22T15:59:01Z',
        model_id: 'served-retry',
        provider_id: 'provider-retry',
        max_output_tokens: null,
        input_price_per_mtok: '1',
        output_price_per_mtok: '2',
        cache_read_price_per_mtok: '0.1',
        cache_write_price_per_mtok: '0.2',
        latency_ms: 300,
        status: 'upstream_error',
        credential_id: 'credential-1',
        credential_scope: 'org',
        credential_name: 'Organization credential',
        token_usage_source: 'unavailable',
        input_tokens: null,
        output_tokens: null,
        cache_read_tokens: null,
        cache_write_tokens: null,
        cost_source: 'unavailable',
        cost_usd: null,
        cost_input_usd: null,
        cost_output_usd: null,
      },
    ],
    denial: null,
    evidence_complete: true,
    confidence: 'partial',
    known_input_tokens: 19,
    known_output_tokens: 7,
    known_cache_read_tokens: 5,
    known_cache_write_tokens: 3,
    known_cost_usd: '0.000000000444',
    token_completeness: 'partial',
    cost_completeness: 'partial',
    ...overrides,
  };
}

function page(items: GatewayRequestReportOut[], nextCursor: string | null = null): GatewayRequestPageOut {
  return { freshness, period, items, page: { next_cursor: nextCursor } };
}

function renderAt(path: string) {
  window.localStorage.setItem('airmux_org_id', ORG.id);
  window.history.replaceState(null, '', path);
  return render(<App />);
}

beforeEach(() => vi.useRealTimers());

describe('request reporting explorer', () => {
  it('renders retries as one logical row and opens URL-selected detail at the list snapshot', async () => {
    let detailAsOf = '';
    server.use(
      http.get('/api/v1/organizations/:orgId/reports/requests', () => HttpResponse.json({ data: page([request()]) })),
      http.get('/api/v1/organizations/:orgId/reports/requests/:requestId', ({ request: detailRequest }) => {
        detailAsOf = new URL(detailRequest.url).searchParams.get('as_of') ?? '';
        return HttpResponse.json({ data: { freshness, request: request() } });
      }),
    );

    const user = userEvent.setup();
    renderAt('/org/requests?timezone=America%2FNew_York');

    expect(await screen.findByRole('heading', { level: 1, name: 'Organization Requests' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Outcome' })).toHaveAttribute('id', 'requests-outcome');
    expect(screen.getByRole('button', { name: 'Confidence' })).toHaveAttribute('id', 'requests-confidence');
    const logicalTable = (await screen.findByRole('heading', { level: 2, name: 'Logical requests' })).closest('section')!;
    expect(within(logicalTable).getAllByRole('row')).toHaveLength(2);
    expect(within(logicalTable).getByText('→ served-final via provider-final')).toBeInTheDocument();
    await user.click(within(logicalTable).getByRole('button', { name: 'View request request-1' }));
    expect(new URLSearchParams(window.location.search).get('request')).toBe('request-1');
    const detail = await screen.findByRole('dialog', { name: 'Request detail' });
    await waitFor(() => expect(detailAsOf).toBe(freshness.as_of));
    expect(within(detail).getByText('Production key')).toBeInTheDocument();
    expect(within(detail).getByText('→ served-final via provider-final')).toBeInTheDocument();
    expect(within(detail).getByText('$0.000000000444 known')).toBeInTheDocument();
    expect(within(detail).getByText('26 known tokens')).toBeInTheDocument();
    expect(within(detail).getByText('Fresh input 11')).toBeInTheDocument();
    expect(within(detail).getByText('Sep 22, 2026, 11:59:01 AM')).toBeInTheDocument();
    expect(within(detail).queryByText('2026-09-22T15:59:01Z')).not.toBeInTheDocument();
    expect(within(detail).getByText('Catalog estimate')).toBeInTheDocument();
    expect(within(detail).getByText('Cost unavailable')).toBeInTheDocument();
    expect(within(detail).queryByText('Fresh input 19')).not.toBeInTheDocument();
  });

  it('opens a deep-linked denied request with denial evidence', async () => {
    const denied = request({
      request_id: 'request-denied',
      terminal: { event_id: 'terminal-denied', occurred_at: '2026-09-22T16:00:00Z', outcome: 'denied', expected_attempts: 0, latency_ms: 4 },
      attempts: [],
      denial: {
        event_id: 'denial-1',
        occurred_at: '2026-09-22T16:00:00Z',
        input_tokens: 0,
        output_tokens: 0,
        cache_read_tokens: 0,
        cache_write_tokens: 0,
        token_usage_source: 'not_applicable',
        cost_source: 'not_applicable',
        cost_usd: '0',
        cost_input_usd: '0',
        cost_output_usd: '0',
        latency_ms: 4,
        status: 'denied',
      },
      confidence: 'not_applicable',
      known_input_tokens: 0,
      known_output_tokens: 0,
      known_cache_read_tokens: 0,
      known_cache_write_tokens: 0,
      known_cost_usd: '0',
      token_completeness: 'complete',
      cost_completeness: 'complete',
    });
    server.use(
      http.get('/api/v1/organizations/:orgId/reports/requests', () => HttpResponse.json({ data: page([denied]) })),
      http.get('/api/v1/organizations/:orgId/reports/requests/:requestId', () => HttpResponse.json({ data: { freshness, request: denied } })),
    );

    renderAt('/org/requests?timezone=UTC&request=request-denied');

    const detail = await screen.findByRole('dialog', { name: 'Request detail' });
    expect(await within(detail).findByRole('heading', { name: 'Denial evidence' })).toBeInTheDocument();
    expect(within(detail).getByText('No routed attempts. Denial evidence is shown below.')).toBeInTheDocument();
    expect(within(detail).getByText('Not applicable · $0.0000')).toBeInTheDocument();
  });

  it('keeps exact zero distinct from unavailable accounting', async () => {
    server.use(
      http.get('/api/v1/organizations/:orgId/reports/requests', () =>
        HttpResponse.json({
          data: page([
            request({
              request_id: 'known-zero',
              attempts: [],
              known_cost_usd: '0',
              known_input_tokens: 0,
              known_output_tokens: 0,
              cost_completeness: 'complete',
              token_completeness: 'complete',
            }),
            request({
              request_id: 'unknown',
              attempts: [],
              known_cost_usd: '0',
              known_input_tokens: 0,
              known_output_tokens: 0,
              cost_completeness: 'unavailable',
              token_completeness: 'unavailable',
            }),
          ]),
        }),
      ),
    );

    renderAt('/org/requests?timezone=UTC');

    await screen.findByRole('heading', { level: 1, name: 'Organization Requests' });
    const logicalTable = (await screen.findByRole('heading', { level: 2, name: 'Logical requests' })).closest('section')!;
    expect(within(logicalTable).getByText('$0.0000')).toBeInTheDocument();
    expect(within(logicalTable).getAllByText('Unavailable')).toHaveLength(2);
  });

  it('propagates repeated filters and resets cursor pagination when a filter changes', async () => {
    const requestedUrls: string[] = [];
    server.use(
      http.get('/api/v1/organizations/:orgId/reports/requests', ({ request: listRequest }) => {
        requestedUrls.push(listRequest.url);
        const cursor = new URL(listRequest.url).searchParams.get('cursor');
        return HttpResponse.json({
          data: cursor ? page([request({ request_id: 'request-2', requested_model_id: 'requested-second' })]) : page([request()], 'next-1'),
        });
      }),
    );
    const user = userEvent.setup();
    renderAt(
      '/org/requests?timezone=UTC&workspace=ws-1&workspace=ws-2&principal=user-1&provider=openai&provider_credential=credential-1' +
        '&outcome=succeeded&confidence=partial&search=100%25_literal&sort=known_cost_usd&direction=asc',
    );

    await screen.findByRole('heading', { level: 2, name: 'Logical requests' });
    await user.click(screen.getByRole('button', { name: 'Load more' }));
    await screen.findByText('requested-second');
    expect(new URL(requestedUrls[0]).searchParams.getAll('workspace')).toEqual(['ws-1', 'ws-2']);
    expect(new URL(requestedUrls[0]).searchParams.get('search')).toBe('100%_literal');
    expect(new URL(requestedUrls[1]).searchParams.get('cursor')).toBe('next-1');

    await user.click(screen.getByRole('combobox', { name: 'Direction' }));
    await user.click(await screen.findByRole('option', { name: 'Desc' }));
    await waitFor(() => expect(requestedUrls.length).toBe(3));
    expect(new URL(requestedUrls[2]).searchParams.has('cursor')).toBe(false);
  });

  it('exports the same filters at the displayed snapshot as a named CSV Blob', async () => {
    let exportUrl = '';
    let download = '';
    const objectUrl = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:requests');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      download = this.download;
    });
    server.use(
      http.get('/api/v1/organizations/:orgId/reports/requests', () => HttpResponse.json({ data: page([request()]) })),
      http.get('/api/v1/organizations/:orgId/reports/request-export', ({ request: exportRequest }) => {
        exportUrl = exportRequest.url;
        return HttpResponse.json({
          data: {
            filename: 'requests.csv',
            content_type: 'text/csv; charset=utf-8',
            row_count: 1,
            freshness,
            period,
            csv: 'request_id\nrequest-1\n',
          },
        });
      }),
    );
    const user = userEvent.setup();
    renderAt('/org/requests?timezone=UTC&provider=openai&outcome=succeeded&search=literal');

    await user.click(await screen.findByRole('button', { name: 'Download CSV' }));
    await waitFor(() => expect(download).toBe('requests.csv'));
    expect(objectUrl).toHaveBeenCalledWith(expect.any(Blob));
    const params = new URL(exportUrl).searchParams;
    expect(params.get('provider')).toBe('openai');
    expect(params.get('outcome')).toBe('succeeded');
    expect(params.get('search')).toBe('literal');
    expect(params.get('as_of')).toBe(freshness.as_of);
  });

  it('uses the workspace endpoint without forwarding an organization workspace filter', async () => {
    let requestedUrl = '';
    server.use(
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/reports/requests', ({ request: listRequest }) => {
        requestedUrl = listRequest.url;
        return HttpResponse.json({ data: page([request()]) });
      }),
    );

    renderAt(`/org/workspaces/${WORKSPACES[0].slug}/requests?timezone=UTC&workspace=ws-other`);

    expect(await screen.findByRole('heading', { level: 1, name: `${WORKSPACES[0].name} Requests` })).toBeInTheDocument();
    expect(new URL(requestedUrl).searchParams.has('workspace')).toBe(false);
  });

  it('does not call request APIs without usage.read', async () => {
    const listRequests = vi.fn(() => HttpResponse.json({ data: page([request()]) }));
    const detailRequest = vi.fn(() => HttpResponse.json({ data: { freshness, request: request() } }));
    const exportRequests = vi.fn(() => HttpResponse.json({ data: { filename: 'requests.csv', row_count: 1, freshness, period, csv: '' } }));
    server.use(
      http.get('/api/v1/auth/permissions', () => HttpResponse.json({ data: { permissions: [Permission.organizationsread] } })),
      http.get('/api/v1/organizations/:orgId/reports/requests', listRequests),
      http.get('/api/v1/organizations/:orgId/reports/requests/:requestId', detailRequest),
      http.get('/api/v1/organizations/:orgId/reports/request-export', exportRequests),
    );

    renderAt('/org/requests?request=request-1');

    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access to this organization page.');
    await waitFor(() => {
      expect(listRequests).not.toHaveBeenCalled();
      expect(detailRequest).not.toHaveBeenCalled();
      expect(exportRequests).not.toHaveBeenCalled();
    });
  });

  it('shows list failures and empty results explicitly', async () => {
    server.use(http.get('/api/v1/organizations/:orgId/reports/requests', () => new HttpResponse(null, { status: 503 })));
    const view = renderAt('/org/requests');
    expect(await screen.findByRole('alert')).toHaveTextContent(/control plane unavailable/i);

    view.unmount();
    server.use(http.get('/api/v1/organizations/:orgId/reports/requests', () => HttpResponse.json({ data: page([]) })));
    renderAt('/org/requests');
    expect(await screen.findByText('No matching logical requests for this period.')).toBeInTheDocument();
  });
});
