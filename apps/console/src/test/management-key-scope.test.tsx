import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { ManagementKeyScope } from '@/components/shared/management-key-scope';
import { TooltipProvider } from '@/components/ui/tooltip';

it('reveals the full workspace target on keyboard focus', async () => {
  const target = '01a09237-aad3-7ac0-84bc-f50e0cf93bed';
  render(
    <TooltipProvider>
      <ManagementKeyScope scope={{ level: 'workspace', org_id: 'org-1', workspace_id: target }} />
    </TooltipProvider>,
  );
  expect(screen.queryByText(target)).not.toBeInTheDocument();
  await userEvent.setup().tab();
  expect(await screen.findByRole('tooltip')).toHaveTextContent(target);
});
