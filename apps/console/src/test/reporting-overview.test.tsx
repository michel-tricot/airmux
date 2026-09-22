import {
  Permission,
  type OverviewReportOut,
  type OverviewMetricsOut,
  type TokenSourceCountsOut,
  type CostSourceCountsOut,
  type OutcomeCountsOut,
} from '@workspace/api-client-react';
import { render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '@/App';
import { ORG, WORKSPACES, server } from './msw';

const sources: TokenSourceCountsOut = { provider: 2, estimated: 0, partial: 0, unavailable: 0, not_applicable: 0 };
const costs: CostSourceCountsOut = { catalog_estimate: 2, unavailable: 0, not_applicable: 0 };
const outcomes: OutcomeCountsOut = { succeeded: 1, failed: 0, denied: 0, timeout: 0, cancelled: 0 };
const zeroSources: TokenSourceCountsOut = { provider: 0, estimated: 0, partial: 0, unavailable: 0, not_applicable: 0 };
const zeroCosts: CostSourceCountsOut = { catalog_estimate: 0, unavailable: 0, not_applicable: 0 };
const zeroOutcomes: OutcomeCountsOut = { succeeded: 0, failed: 0, denied: 0, timeout: 0, cancelled: 0 };

function metrics(overrides: Partial<OverviewMetricsOut> = {}): OverviewMetricsOut {
  return {
    logical_requests: 1,
    attempts: 2,
    outcomes,
    pending_requests: 0,
    incomplete_requests: 0,
    known_input_tokens: 12,
    known_output_tokens: 8,
    known_cache_read_tokens: 3,
    known_cache_write_tokens: 2,
    unavailable_usage_attempts: 0,
    token_sources: sources,
    known_cost_usd: '0.000000000444',
    unpriced_attempts: 0,
    cost_sources: costs,
    cost_per_request_usd: '0.000000000444',
    cost_per_request_denominator: 1,
    token_completeness: 'complete',
    cost_completeness: 'complete',
    ...overrides,
  };
}

function report(overrides: Partial<OverviewReportOut> = {}): OverviewReportOut {
  const current = metrics();
  return {
    freshness: { as_of: 'snapshot-1', watermark: 'watermark-1', received_at: '2026-09-22T16:00:00Z', delivery_completeness: 'unavailable' },
    periods: {
      current: { start_at: '2026-09-16T00:00:00Z', end_at: '2026-09-22T16:00:00Z', timezone: 'UTC' },
      comparison: { start_at: '2026-09-09T08:00:00Z', end_at: '2026-09-16T00:00:00Z', timezone: 'UTC' },
    },
    bucket: 'day',
    split: 'none',
    group: 'workspace',
    summary: {
      current,
      comparison: metrics({
        logical_requests: 0,
        attempts: 0,
        outcomes: zeroOutcomes,
        known_input_tokens: 0,
        known_output_tokens: 0,
        known_cache_read_tokens: 0,
        known_cache_write_tokens: 0,
        token_sources: zeroSources,
        known_cost_usd: '0',
        cost_sources: zeroCosts,
        cost_per_request_usd: null,
        cost_per_request_denominator: 0,
      }),
      delta: {
        logical_requests: 1,
        attempts: 2,
        outcomes,
        pending_requests: 0,
        incomplete_requests: 0,
        known_input_tokens: 12,
        known_output_tokens: 8,
        known_cache_read_tokens: 3,
        known_cache_write_tokens: 2,
        unavailable_usage_attempts: 0,
        token_sources: sources,
        known_cost_usd: '0.000000000444',
        unpriced_attempts: 0,
        cost_sources: costs,
        cost_per_request_usd: null,
      },
    },
    series: [
      {
        start_at: '2026-09-22T15:00:00Z',
        end_at: '2026-09-22T16:00:00Z',
        split_id: null,
        split_label: 'All',
        metrics: current,
      },
    ],
    attribution: [
      {
        id: WORKSPACES[0].id,
        label: WORKSPACES[0].name,
        share_of_known_cost: '1',
        summary: {
          current,
          comparison: metrics({
            logical_requests: 0,
            attempts: 0,
            outcomes: zeroOutcomes,
            known_input_tokens: 0,
            known_output_tokens: 0,
            known_cache_read_tokens: 0,
            known_cache_write_tokens: 0,
            token_sources: zeroSources,
            known_cost_usd: '0',
            cost_sources: zeroCosts,
            cost_per_request_usd: null,
            cost_per_request_denominator: 0,
          }),
          delta: {
            logical_requests: 1,
            attempts: 2,
            outcomes,
            pending_requests: 0,
            incomplete_requests: 0,
            known_input_tokens: 12,
            known_output_tokens: 8,
            known_cache_read_tokens: 3,
            known_cache_write_tokens: 2,
            unavailable_usage_attempts: 0,
            token_sources: sources,
            known_cost_usd: '0.000000000444',
            unpriced_attempts: 0,
            cost_sources: costs,
            cost_per_request_usd: null,
          },
        },
      },
    ],
    ...overrides,
  };
}

function renderAt(path: string) {
  window.localStorage.setItem('airmux_org_id', ORG.id);
  window.history.replaceState(null, '', path);
  return render(<App />);
}

beforeEach(() => vi.useRealTimers());

describe('shared spending overview', () => {
  it('keeps the organization overview at /org and counts retries once', async () => {
    const orgReport = vi.fn(() => HttpResponse.json({ data: report() }));
    const events = vi.fn(() => new HttpResponse(null, { status: 500 }));
    server.use(http.get('/api/v1/organizations/:orgId/reports/overview', orgReport), http.get('/api/v1/organizations/:orgId/events', events));

    renderAt('/org');

    expect(await screen.findByRole('heading', { level: 1, name: 'Organization Overview' })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/org');
    expect(screen.getByRole('combobox', { name: 'Workspace' })).toHaveTextContent('All workspaces');
    const requests = (await screen.findByText('Logical requests', { selector: 'div' })).parentElement!;
    expect(within(requests).getByText('1')).toBeInTheDocument();
    expect(within(requests).getByText(/2 attempts/)).toBeInTheDocument();
    expect(within(screen.getByText('Known spend', { selector: 'div' }).parentElement!).getByText('$0.000000000444')).toBeInTheDocument();
    expect(screen.getByText('Production')).toBeInTheDocument();
    expect(screen.getByText('100.00%')).toBeInTheDocument();
    const attribution = screen.getByRole('heading', { level: 2, name: 'Attribution' }).closest('section')!;
    expect(within(attribution).getByRole('columnheader', { name: 'Period change' })).toBeInTheDocument();
    expect(within(attribution).getByRole('columnheader', { name: 'Known tokens' })).toBeInTheDocument();
    expect(within(attribution).getByRole('columnheader', { name: 'Cost per request' })).toBeInTheDocument();
    expect(within(attribution).getByText('+$0.000000000444')).toBeInTheDocument();
    await waitFor(() => expect(orgReport).toHaveBeenCalled());
    expect(events).not.toHaveBeenCalled();
  });

  it('formats high-precision attribution shares without discarding valid data', async () => {
    const base = report();
    server.use(
      http.get('/api/v1/organizations/:orgId/reports/overview', () =>
        HttpResponse.json({
          data: report({ attribution: [{ ...base.attribution[0], share_of_known_cost: '0.748741234567890123' }] }),
        }),
      ),
    );

    renderAt('/org');

    expect(await screen.findByText('74.87%')).toBeInTheDocument();
  });

  it('uses the workspace report with the same rendering', async () => {
    const workspaceReport = vi.fn(() => HttpResponse.json({ data: report() }));
    server.use(http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/reports/overview', workspaceReport));

    renderAt(`/org/workspaces/${WORKSPACES[0].slug}`);

    expect(await screen.findByRole('heading', { level: 1, name: WORKSPACES[0].name })).toBeInTheDocument();
    expect(screen.getByText('Gateway-observed estimated spending and usage for this workspace.')).toBeInTheDocument();
    expect((await screen.findAllByRole('columnheader', { name: 'Known spend' })).length).toBe(2);
    await waitFor(() => expect(workspaceReport).toHaveBeenCalled());
  });

  it('does not present unavailable accounting as complete zero', async () => {
    const unavailable = metrics({
      known_input_tokens: 0,
      known_output_tokens: 0,
      known_cache_read_tokens: 0,
      known_cache_write_tokens: 0,
      unavailable_usage_attempts: 1,
      token_sources: { provider: 0, estimated: 0, partial: 0, unavailable: 1, not_applicable: 0 },
      known_cost_usd: '0',
      unpriced_attempts: 1,
      cost_sources: { catalog_estimate: 0, unavailable: 1, not_applicable: 0 },
      cost_per_request_usd: '0.000000000000',
      token_completeness: 'unavailable',
      cost_completeness: 'unavailable',
    });
    const unavailableReport = report({
      summary: { ...report().summary, current: unavailable },
      series: [{ ...report().series[0], metrics: unavailable }],
      attribution: [
        {
          ...report().attribution[0],
          share_of_known_cost: null,
          summary: { ...report().attribution[0].summary, current: unavailable },
        },
      ],
    });
    server.use(http.get('/api/v1/organizations/:orgId/reports/overview', () => HttpResponse.json({ data: unavailableReport })));

    renderAt('/org');

    expect(await screen.findByRole('heading', { level: 1, name: 'Organization Overview' })).toBeInTheDocument();
    const spend = (await screen.findByText('Known spend', { selector: 'div' })).parentElement!;
    const tokens = screen.getByText('Known tokens', { selector: 'div' }).parentElement!;
    expect(within(spend).getByText('Unavailable', { selector: '.text-2xl' })).toBeInTheDocument();
    expect(within(tokens).getByText('Unavailable', { selector: '.text-2xl' })).toBeInTheDocument();
    expect(screen.queryByText('$0.0000')).not.toBeInTheDocument();
    expect(screen.getByText(/1 unpriced attempt/)).toBeInTheDocument();
  });

  it('renders a missing receipt timestamp as unavailable', async () => {
    server.use(
      http.get('/api/v1/organizations/:orgId/reports/overview', () =>
        HttpResponse.json({ data: report({ freshness: { ...report().freshness, received_at: null } }) }),
      ),
    );

    renderAt('/org');

    expect(await screen.findByRole('heading', { level: 1, name: 'Organization Overview' })).toBeInTheDocument();
    expect((await screen.findByText('Receipt')).parentElement).toHaveTextContent('Unavailable');
  });

  it('keeps known partial values visible and qualified', async () => {
    const partial = metrics({
      token_completeness: 'partial',
      cost_completeness: 'partial',
      unavailable_usage_attempts: 1,
      unpriced_attempts: 1,
      token_sources: { provider: 1, estimated: 0, partial: 1, unavailable: 0, not_applicable: 0 },
      cost_sources: { catalog_estimate: 1, unavailable: 1, not_applicable: 0 },
    });
    server.use(
      http.get('/api/v1/organizations/:orgId/reports/overview', () =>
        HttpResponse.json({ data: report({ summary: { ...report().summary, current: partial } }) }),
      ),
    );

    renderAt('/org');

    const spend = (await screen.findByText('Known spend', { selector: 'div' })).parentElement!;
    const tokens = screen.getByText('Known tokens', { selector: 'div' }).parentElement!;
    expect(within(spend).getByText('$0.000000000444 known')).toBeInTheDocument();
    expect(within(spend).getByText('Partial')).toBeInTheDocument();
    expect(within(tokens).getByText('20 known')).toBeInTheDocument();
    expect(within(tokens).getByText('Partial')).toBeInTheDocument();
  });

  it('passes URL-backed repeated filters to the generated report request', async () => {
    let requestedUrl = '';
    server.use(
      http.get('/api/v1/organizations/:orgId/reports/overview', ({ request }) => {
        requestedUrl = request.url;
        return HttpResponse.json({ data: report() });
      }),
    );

    renderAt(
      '/org?range=custom&timezone=UTC&start_date=2026-09-01&end_date=2026-09-22&bucket=hour&split=model&group=provider_credential' +
        '&workspace=ws-1&workspace=ws-2&principal=user-1&inference_key=key-1&model=gpt-4o&model=claude&provider=openai',
    );

    await screen.findByRole('heading', { level: 1, name: 'Organization Overview' });
    const params = new URL(requestedUrl).searchParams;
    expect(params.get('range')).toBe('custom');
    expect(params.get('bucket')).toBe('hour');
    expect(params.get('group')).toBe('provider_credential');
    expect(params.getAll('workspace')).toEqual(['ws-1', 'ws-2']);
    expect(params.getAll('model')).toEqual(['gpt-4o', 'claude']);
    expect(params.getAll('provider')).toEqual(['openai']);
    expect(screen.getByRole('combobox', { name: 'Attribution group' })).toHaveTextContent('Provider credential');
  });

  it('builds snapshot-pinned total and provider credential drilldowns from active analytical filters', async () => {
    const base = report();
    server.use(
      http.get('/api/v1/organizations/:orgId/reports/overview', () =>
        HttpResponse.json({
          data: report({
            group: 'provider_credential',
            attribution: [{ ...base.attribution[0], id: null, label: 'Unattributed' }],
          }),
        }),
      ),
    );
    renderAt(
      '/org?range=custom&timezone=UTC&start_date=2026-09-01&end_date=2026-09-22&bucket=hour&split=provider&group=provider_credential' +
        '&workspace=ws-1&principal=user-1&model=model-1&provider=openai',
    );

    const total = await screen.findByRole('link', { name: 'View matching requests' });
    const totalParams = new URL(total.getAttribute('href')!, 'http://console.test').searchParams;
    expect(totalParams.get('as_of')).toBe('snapshot-1');
    expect(totalParams.getAll('workspace')).toEqual(['ws-1']);
    expect(totalParams.get('principal')).toBe('user-1');
    expect(totalParams.get('model')).toBe('model-1');
    expect(totalParams.get('provider')).toBe('openai');
    expect(totalParams.has('bucket')).toBe(false);
    expect(totalParams.has('split')).toBe(false);
    expect(totalParams.has('group')).toBe(false);

    const unattributed = screen.getByRole('link', { name: 'Unattributed' });
    const attributionParams = new URL(unattributed.getAttribute('href')!, 'http://console.test').searchParams;
    expect(attributionParams.getAll('provider_credential')).toEqual(['unattributed']);
  });

  it('does not invent unattributed model or provider drilldowns', async () => {
    const base = report();
    server.use(
      http.get('/api/v1/organizations/:orgId/reports/overview', () =>
        HttpResponse.json({
          data: report({ group: 'model', attribution: [{ ...base.attribution[0], id: null, label: 'Unknown model' }] }),
        }),
      ),
    );
    renderAt('/org?group=model');

    expect(await screen.findByText('Unknown model')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Unknown model' })).not.toBeInTheDocument();
  });

  it('does not request reporting without usage.read', async () => {
    const orgReport = vi.fn(() => HttpResponse.json({ data: report() }));
    server.use(
      http.get('/api/v1/auth/permissions', () => HttpResponse.json({ data: { permissions: ['organizations.read', 'workspaces.read'] } })),
      http.get('/api/v1/organizations/:orgId/reports/overview', orgReport),
    );

    renderAt('/org');

    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have permission to view organization usage.');
    await waitFor(() => expect(orgReport).not.toHaveBeenCalled());
  });

  it('does not request workspace reporting without workspace usage.read', async () => {
    const workspaceReport = vi.fn(() => HttpResponse.json({ data: report() }));
    server.use(
      http.get('/api/v1/auth/permissions', ({ request }) => {
        const workspaceScope = new URL(request.url).searchParams.has('workspace_ref');
        return HttpResponse.json({
          data: { permissions: workspaceScope ? ['workspaces.read'] : Object.values(Permission) },
        });
      }),
      http.get('/api/v1/organizations/:orgId/workspaces/:workspaceRef/reports/overview', workspaceReport),
    );

    renderAt(`/org/workspaces/${WORKSPACES[0].slug}`);

    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have permission to view workspace usage.');
    await waitFor(() => expect(workspaceReport).not.toHaveBeenCalled());
  });

  it('shows report errors and empty results explicitly', async () => {
    server.use(http.get('/api/v1/organizations/:orgId/reports/overview', () => new HttpResponse(null, { status: 503 })));
    const view = renderAt('/org');
    expect(await screen.findByRole('alert')).toHaveTextContent(/control plane unavailable/i);

    view.unmount();
    server.use(
      http.get('/api/v1/organizations/:orgId/reports/overview', () =>
        HttpResponse.json({
          data: report({
            summary: {
              ...report().summary,
              current: metrics({
                logical_requests: 0,
                attempts: 0,
                known_cost_usd: '0',
                cost_per_request_usd: null,
                cost_per_request_denominator: 0,
              }),
            },
            series: [],
            attribution: [],
          }),
        }),
      ),
    );
    renderAt('/org');
    expect(await screen.findByText('No matching gateway requests for this period.')).toBeInTheDocument();
  });

  it('keeps comparison-only attribution visible when the current period is empty', async () => {
    const empty = metrics({
      logical_requests: 0,
      attempts: 0,
      outcomes: zeroOutcomes,
      known_input_tokens: 0,
      known_output_tokens: 0,
      known_cache_read_tokens: 0,
      known_cache_write_tokens: 0,
      token_sources: zeroSources,
      known_cost_usd: '0',
      cost_sources: zeroCosts,
      cost_per_request_usd: null,
      cost_per_request_denominator: 0,
    });
    const prior = metrics({ known_cost_usd: '1.234560000001', cost_per_request_usd: '1.234560000001' });
    const base = report();
    server.use(
      http.get('/api/v1/organizations/:orgId/reports/overview', () =>
        HttpResponse.json({
          data: report({
            summary: { ...base.summary, current: empty },
            series: [],
            attribution: [
              {
                id: 'former-workspace',
                label: 'Former workspace',
                share_of_known_cost: null,
                summary: {
                  current: empty,
                  comparison: prior,
                  delta: {
                    ...base.summary.delta,
                    logical_requests: -1,
                    attempts: -2,
                    known_cost_usd: '-1.234560000001',
                    cost_per_request_usd: '-1.234560000001',
                  },
                },
              },
            ],
          }),
        }),
      ),
    );

    renderAt('/org');

    expect(await screen.findByText('No matching gateway requests for this period.')).toBeInTheDocument();
    const attribution = screen.getByRole('heading', { level: 2, name: 'Attribution' }).closest('section')!;
    expect(within(attribution).getByText('Former workspace')).toBeInTheDocument();
    expect(within(attribution).getByText('-$1.234560000001')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2, name: 'Trend' })).not.toBeInTheDocument();
  });
});
