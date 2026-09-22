import type { OverviewMetricsOut, OverviewReportOut, OverviewSeriesPointOut } from '@workspace/api-client-react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { OverviewTimeSeries } from './overview-time-series';

const metrics = (overrides: Partial<OverviewMetricsOut> = {}): OverviewMetricsOut => ({
  logical_requests: 2,
  attempts: 3,
  outcomes: { succeeded: 2, failed: 0, denied: 0, timeout: 0, cancelled: 0 },
  pending_requests: 0,
  incomplete_requests: 0,
  known_input_tokens: 10,
  known_output_tokens: 5,
  known_cache_read_tokens: 1_000,
  known_cache_write_tokens: 2_000,
  unavailable_usage_attempts: 0,
  token_sources: { provider: 3, estimated: 0, partial: 0, unavailable: 0, not_applicable: 0 },
  known_cost_usd: '0.000000000444',
  unpriced_attempts: 0,
  cost_sources: { catalog_estimate: 3, unavailable: 0, not_applicable: 0 },
  cost_per_request_usd: '0.000000000222',
  cost_per_request_denominator: 2,
  token_completeness: 'complete',
  cost_completeness: 'complete',
  ...overrides,
});

const point = (
  start: string,
  end: string,
  splitId: string,
  splitLabel: string,
  overrides: Partial<OverviewMetricsOut> = {},
): OverviewSeriesPointOut => ({
  start_at: start,
  end_at: end,
  split_id: splitId,
  split_label: splitLabel,
  metrics: metrics(overrides),
});

const series = [
  point('2026-09-20T00:00:00Z', '2026-09-21T00:00:00Z', 'model-a', 'Model A'),
  point('2026-09-22T00:00:00Z', '2026-09-23T00:00:00Z', 'model-a', 'Model A', {
    known_cost_usd: '0.25',
    token_completeness: 'partial',
  }),
  point('2026-09-20T00:00:00Z', '2026-09-21T00:00:00Z', 'model-b', 'Model B', {
    logical_requests: 1,
    known_input_tokens: 0,
    known_output_tokens: 0,
    token_completeness: 'unavailable',
    known_cost_usd: '0',
    cost_completeness: 'unavailable',
  }),
];

const report: OverviewReportOut = {
  freshness: { as_of: 'snapshot-1', watermark: null, received_at: null, delivery_completeness: 'unavailable' },
  periods: {
    current: { start_at: '2026-09-20T00:00:00Z', end_at: '2026-09-23T00:00:00Z', timezone: 'UTC' },
    comparison: { start_at: '2026-09-17T00:00:00Z', end_at: '2026-09-20T00:00:00Z', timezone: 'UTC' },
  },
  bucket: 'day',
  split: 'model',
  group: 'model',
  summary: {
    current: metrics(),
    comparison: metrics(),
    delta: {
      logical_requests: 0,
      attempts: 0,
      outcomes: { succeeded: 0, failed: 0, denied: 0, timeout: 0, cancelled: 0 },
      pending_requests: 0,
      incomplete_requests: 0,
      known_input_tokens: 0,
      known_output_tokens: 0,
      known_cache_read_tokens: 0,
      known_cache_write_tokens: 0,
      unavailable_usage_attempts: 0,
      token_sources: { provider: 0, estimated: 0, partial: 0, unavailable: 0, not_applicable: 0 },
      known_cost_usd: '0',
      unpriced_attempts: 0,
      cost_sources: { catalog_estimate: 0, unavailable: 0, not_applicable: 0 },
      cost_per_request_usd: null,
    },
  },
  series,
  attribution: [],
};

describe('overview time series', () => {
  it('switches exact metrics and exposes split series and point labels', async () => {
    const user = userEvent.setup();
    const view = render(<OverviewTimeSeries report={report} />);

    expect(screen.getByRole('list', { name: 'Trend series' })).toHaveTextContent('Model A');
    expect(screen.getByRole('list', { name: 'Trend series' })).toHaveTextContent('Model B');
    expect(view.container.querySelector('circle[aria-label*="$0.000000000444"]')).not.toBeNull();
    expect(view.container.querySelector('circle[aria-label*="Unavailable"]')).toBeNull();

    await user.click(screen.getByRole('tab', { name: 'Requests' }));
    expect(view.container.querySelector('circle[aria-label*="2 logical requests"]')).not.toBeNull();

    await user.click(screen.getByRole('tab', { name: 'Tokens' }));
    expect(view.container.querySelector('circle[aria-label*="15 tokens"]')).not.toBeNull();
    expect(view.container.querySelector('circle[aria-label*="3015"]')).toBeNull();
    expect(view.container.querySelector('circle[aria-label*="15 known tokens"]')).not.toBeNull();
    expect(view.container.querySelector('circle[aria-label*="Partial accounting"]')).not.toBeNull();
    expect(view.container.querySelector('circle[aria-label*="Partial accounting"][fill="none"][stroke="currentColor"]')).not.toBeNull();
    expect(screen.getByRole('list', { name: 'Trend series' })).toHaveTextContent('Hollow marker: partial accounting');
  });

  it('breaks sparse series instead of drawing across missing buckets', () => {
    const view = render(<OverviewTimeSeries report={report} />);
    const modelAChart = screen.getByRole('group', { name: 'Model A spend trend' });

    expect(modelAChart.querySelectorAll('path[stroke="currentColor"]')).toHaveLength(2);
    expect(view.container.querySelectorAll('circle[aria-label*="Model A"]')).toHaveLength(2);
  });

  it('keeps an exact accessible data table for every metric', () => {
    render(<OverviewTimeSeries report={report} />);
    const table = screen.getByRole('table');

    expect(within(table).getByRole('columnheader', { name: 'Known spend' })).toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: 'Logical requests' })).toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: 'Known tokens' })).toBeInTheDocument();
    expect(within(table).getByText('$0.000000000444')).toBeInTheDocument();
    expect(within(table).getAllByText('Unavailable')).toHaveLength(2);
  });
});
