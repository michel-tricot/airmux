import { render, screen } from '@testing-library/react';
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
  expect(screen.getByText('Includes future API keys and playground sessions.')).toBeVisible();
});
