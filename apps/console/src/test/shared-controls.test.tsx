import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Link } from 'wouter';
import { Button, ConfirmButton } from '@/components/ui/elements';
describe('shared controls', () => {
  it('composes button styling onto navigation without nesting interactive controls', () => {
    render(
      <Button asChild>
        <Link href="/next">Continue</Link>
      </Button>,
    );

    const link = screen.getByRole('link', { name: 'Continue' });
    expect(link.closest('button')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Continue' })).not.toBeInTheDocument();
  });

  it('uses alert-dialog semantics and stays open when confirmation fails', async () => {
    const user = userEvent.setup();
    render(
      <ConfirmButton title="Delete organization" onConfirm={() => Promise.reject(new Error('failed'))}>
        Delete
      </ConfirmButton>,
    );

    await user.click(screen.getByRole('button', { name: 'Delete' }));
    const dialog = screen.getByRole('alertdialog', { name: 'Delete organization' });
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    expect(screen.getByRole('alertdialog', { name: 'Delete organization' })).toBeInTheDocument();
  });
});
