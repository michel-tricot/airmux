import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { PolicyEditor } from '@/pages/app/workspace/PolicyEditor';

it('keeps the key target label short and explains its scope outside the dropdown', () => {
  render(
    <PolicyEditor
      policy={null}
      open
      onOpenChange={() => {}}
      onSubmit={async () => {}}
      pending={false}
      keys={[]}
      catalog={{ providers: [], models: [] }}
    />,
  );

  expect(screen.getByRole('combobox', { name: 'Applies to' })).toHaveTextContent(/^All keys$/);
  expect(screen.getByText('Includes future inference keys and playground sessions.')).toBeVisible();
});

it('adds and removes rules while keeping one required rule', async () => {
  const user = userEvent.setup();
  render(
    <PolicyEditor
      policy={null}
      open
      onOpenChange={() => {}}
      onSubmit={async () => {}}
      pending={false}
      keys={[]}
      catalog={{ providers: [], models: [] }}
    />,
  );

  expect(screen.getByRole('button', { name: 'Remove rule 1' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'Add rule' }));
  expect(screen.getByText('Rule 2')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Remove rule 2' }));
  expect(screen.queryByText('Rule 2')).not.toBeInTheDocument();
});
