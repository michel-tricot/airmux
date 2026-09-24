import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { ReportingChart } from '@/components/shared/reporting-chart';
import { TooltipProvider } from '@/components/ui/tooltip';

it('labels dates across the trend and shows full daily usage on hover', async () => {
  const daily = Array.from({ length: 5 }, (_, index) => ({
    date: `2026-01-0${index + 1}T00:00:00Z`,
    requests: index + 1,
    input_tokens: 10 + index,
    output_tokens: 3 + index,
    cache_read_tokens: 2,
    cache_write_tokens: 1,
    cost_usd: '1.25',
  }));
  render(
    <TooltipProvider delayDuration={0}>
      <ReportingChart
        daily={daily}
        period="30d"
        metric="cost"
        search={new URLSearchParams()}
        endAt="2026-01-06T00:00:00Z"
        timezone="UTC"
        onMetricChange={() => {}}
      />
    </TooltipProvider>,
  );

  expect(screen.getByText('Jan 1')).toBeInTheDocument();
  expect(screen.getByText('Jan 3')).toBeInTheDocument();
  expect(screen.getByText('Jan 5')).toBeInTheDocument();
  const chart = screen.getByRole('img', { name: 'cost over time' });
  const firstPoint = within(chart.parentElement as HTMLElement).getAllByRole('link')[0];
  await userEvent.setup().hover(firstPoint);
  const date = await screen.findByText('Thursday, January 1, 2026');
  expect(date).toHaveClass('whitespace-nowrap');
  expect(date.closest('[role="tooltip"]')).toHaveClass('w-max');
  expect(screen.getByText('Requests')).toBeInTheDocument();
  expect(screen.getByText('Input tokens')).toBeInTheDocument();
  expect(screen.getByText('Output tokens')).toBeInTheDocument();
  expect(screen.getAllByText('$1.25').length).toBeGreaterThan(0);
});

it('labels a one-day custom report as a date, not an hour', () => {
  render(
    <TooltipProvider>
      <ReportingChart
        daily={[
          {
            date: '2026-01-01T00:00:00Z',
            requests: 1,
            input_tokens: 1,
            output_tokens: 0,
            cache_read_tokens: 0,
            cache_write_tokens: 0,
            cost_usd: '1',
          },
        ]}
        period="custom"
        metric="requests"
        search={new URLSearchParams()}
        endAt="2026-01-02T00:00:00Z"
        timezone="UTC"
        onMetricChange={() => {}}
      />
    </TooltipProvider>,
  );
  expect(screen.getByText('Jan 1')).toBeInTheDocument();
  expect(screen.queryByText('12:00 AM')).not.toBeInTheDocument();
});
