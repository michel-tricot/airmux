import { useState } from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { ReportingFilters } from './reporting-filters';

function TestReportingFilters() {
  const [startDate, setStartDate] = useState('2026-08-24');
  return (
    <ReportingFilters
      period="custom"
      timezone="UTC"
      startDate={startDate}
      endDate="2026-09-22"
      selected={() => ''}
      options={{ workspace: [], owner: [], key: [], model: [], provider: [], credential: [] }}
      onChange={(name, value) => {
        if (name === 'start_date') setStartDate(value);
      }}
      onClear={() => {}}
    />
  );
}

it('opens a themed calendar and selects a reporting date', async () => {
  const user = userEvent.setup();
  render(<TestReportingFilters />);

  await user.click(screen.getByRole('button', { name: 'Choose start date, August 24, 2026' }));
  const calendar = screen.getByRole('dialog', { name: 'Start date' });
  expect(calendar).toHaveClass('bg-card', 'text-card-foreground');
  await user.click(within(calendar).getByRole('button', { name: 'August 25, 2026' }));

  expect(screen.getByRole('button', { name: 'Choose start date, August 25, 2026' })).toBeInTheDocument();
  expect(screen.queryByRole('dialog', { name: 'Start date' })).not.toBeInTheDocument();
});

it('accepts a directly entered date outside the displayed month', async () => {
  const user = userEvent.setup();
  render(<TestReportingFilters />);

  await user.click(screen.getByRole('button', { name: 'Choose start date, August 24, 2026' }));
  const calendar = screen.getByRole('dialog', { name: 'Start date' });
  await user.clear(within(calendar).getByRole('textbox', { name: 'Date in YYYY-MM-DD format' }));
  await user.type(within(calendar).getByRole('textbox', { name: 'Date in YYYY-MM-DD format' }), '2020-02-30');
  await user.click(within(calendar).getByRole('button', { name: 'Apply date' }));
  expect(within(calendar).getByRole('alert')).toHaveTextContent('Enter a valid date');
  await user.clear(within(calendar).getByRole('textbox', { name: 'Date in YYYY-MM-DD format' }));
  await user.type(within(calendar).getByRole('textbox', { name: 'Date in YYYY-MM-DD format' }), '2020-01-01');
  await user.click(within(calendar).getByRole('button', { name: 'Apply date' }));

  expect(screen.getByRole('button', { name: 'Choose start date, January 1, 2020' })).toBeInTheDocument();
});
