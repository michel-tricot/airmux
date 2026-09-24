import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { DetailSheet } from '@/components/shared/detail-sheet';

it('renders arbitrary detail content and closes through the shared sheet', async () => {
  let open = true;
  const onOpenChange = (next: boolean) => {
    open = next;
  };
  render(
    <DetailSheet open={open} onOpenChange={onOpenChange} title="Credential details" description="Production credential">
      <p>Example data</p>
    </DetailSheet>,
  );

  const panel = screen.getByRole('dialog', { name: 'Credential details' });
  expect(panel).toHaveClass('p-6');
  expect(within(panel).getByText('Production credential')).toBeInTheDocument();
  expect(within(panel).getByText('Example data')).toBeInTheDocument();
  await userEvent.setup().click(within(panel).getByRole('button', { name: 'Close' }));
  expect(open).toBe(false);
});
