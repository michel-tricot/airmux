import { render, screen } from '@testing-library/react';
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
  const firstPoint = screen.getByRole('img', { name: 'cost over time' }).querySelector('circle[aria-label]');
  expect(firstPoint).not.toBeNull();
  await userEvent.setup().hover(firstPoint!);
  expect(await screen.findByText('Thursday, January 1, 2026')).toBeInTheDocument();
  expect(screen.getByText('Requests')).toBeInTheDocument();
  expect(screen.getByText('Input tokens')).toBeInTheDocument();
  expect(screen.getByText('Output tokens')).toBeInTheDocument();
  expect(screen.getByText('$1.25')).toBeInTheDocument();
});
