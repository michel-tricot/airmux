import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { ReportRefreshButton } from './report-refresh-button';

function Reports() {
  const [usage, setUsage] = useState(0);
  const [attribution, setAttribution] = useState(0);

  return (
    <>
      <ReportRefreshButton
        queries={[
          { isFetching: false, refetch: () => setUsage((count) => count + 1) },
          { isFetching: true, refetch: () => setAttribution((count) => count + 1) },
        ]}
      />
      <output>{`${usage} usage and ${attribution} attribution refreshes`}</output>
    </>
  );
}

it('refreshes every supplied report and shows fetching on the shared control', async () => {
  render(<Reports />);

  const button = screen.getByRole('button', { name: 'Refresh' });
  expect(button.querySelector('svg')).toHaveClass('motion-safe:animate-spin');

  await userEvent.setup().click(button);

  expect(screen.getByText('1 usage and 1 attribution refreshes')).toBeInTheDocument();
});

it('shows refresh feedback even when a report finishes before its fetching state is visible', async () => {
  render(<ReportRefreshButton queries={[{ isFetching: false, refetch: () => undefined }]} />);

  const button = screen.getByRole('button', { name: 'Refresh' });
  await userEvent.setup().click(button);

  expect(button.querySelector('svg')).toHaveClass('motion-safe:animate-spin');
  await waitFor(() => expect(button.querySelector('svg')).not.toHaveClass('motion-safe:animate-spin'));
});
