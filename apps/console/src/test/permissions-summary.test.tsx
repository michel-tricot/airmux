import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { PermissionsCell } from '@/components/shared/permissions-cell';
import { TooltipProvider } from '@/components/ui/tooltip';

it('summarizes extra permission groups and exposes the complete list on focus', async () => {
  render(
    <TooltipProvider>
      <PermissionsCell permissions={['data-planes.read', 'inference-keys.read', 'members.read']} />
    </TooltipProvider>,
  );
  expect(screen.getByText('+2 more')).toBeInTheDocument();
  expect(screen.queryByText('members')).not.toBeInTheDocument();
  await userEvent.setup().tab();
  expect(await screen.findByRole('tooltip')).toHaveTextContent('members');
  expect(screen.getByRole('tooltip')).toHaveTextContent('inference-keys');
});
