import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Link } from 'wouter';
import { Badge, Button, Card, ConfirmButton, Dropdown, Modal, Switch, Table } from '@/components/ui/elements';
describe('shared controls', () => {
  it.each(['default', 'secondary', 'destructive', 'success', 'warning', 'outline', 'mono'] as const)(
    'uses consistent optical text alignment for %s badges',
    (variant) => {
      render(<Badge variant={variant}>ACTIVE</Badge>);

      expect(screen.getByText('ACTIVE')).toHaveClass('h-5', 'items-center', 'justify-center', 'leading-none', 'pt-0.5', 'pb-0');
    },
  );

  it.each([
    [false, 'translate-x-1'],
    [true, 'translate-x-4.5'],
  ] as const)('keeps equal thumb insets when the switch is checked=%s', (checked, position) => {
    render(<Switch checked={checked} onCheckedChange={() => {}} aria-label="Enabled" />);

    const toggle = screen.getByRole('switch', { name: 'Enabled', checked });
    expect(toggle).toHaveClass('w-9');
    expect(toggle.querySelector('span')).toHaveClass('w-3.5', position);
  });

  it('uses a shrinkable dialog column for long form selections', () => {
    const label = 'All keys, including future keys and playground sessions';
    render(
      <Modal open onOpenChange={() => {}} title="Policy" description="Configure inference access">
        <form>
          <Dropdown value="all" onValueChange={() => {}} options={[{ value: 'all', label }]} aria-label="Applies to" />
        </form>
      </Modal>,
    );

    expect(screen.getByRole('dialog', { name: 'Policy' })).toHaveClass('grid-cols-1');
    expect(screen.getByRole('combobox', { name: 'Applies to' })).toHaveTextContent(label);
    expect(screen.getByRole('combobox', { name: 'Applies to' })).toHaveClass('leading-normal');
  });

  it('fits the status choices without an unnecessary scroll affordance', async () => {
    const user = userEvent.setup();
    render(
      <Dropdown
        value="all"
        onValueChange={() => {}}
        options={['All statuses', 'Succeeded', 'Denied', 'Upstream error', 'Credential rejected', 'Timeout', 'Rate limited', 'Cancelled'].map(
          (label) => ({ value: label === 'All statuses' ? 'all' : label, label }),
        )}
        aria-label="Status"
      />,
    );

    await user.click(screen.getByRole('combobox', { name: 'Status' }));
    expect(screen.getByRole('listbox')).toHaveClass('[&_[data-radix-select-viewport]]:max-h-96');
  });

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

  it('uses one thin border when a table is the card surface', () => {
    render(
      <Card data-testid="card">
        <Table aria-label="Models" />
      </Card>,
    );

    expect(screen.getByTestId('card')).toHaveClass('[&>[data-slot=table-surface]]:border-0');
    expect(screen.getByRole('table', { name: 'Models' }).parentElement?.parentElement).toHaveAttribute('data-slot', 'table-surface');
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
