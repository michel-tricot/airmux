import type * as Api from '@workspace/api-client-react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { RuleEditor } from '@/pages/app/workspace/RuleEditor';
import { now, taxonomyProvider } from './fixtures';

const provider = taxonomyProvider('provider-1', 'openai');
const model = {
  id: 'model-1',
  name: 'openai/gpt-test',
  provider_id: provider.id,
  upstream_model: 'gpt-test',
  egress_kind: null,
  input_price_per_mtok: 1,
  output_price_per_mtok: 2,
  cache_read_price_per_mtok: 0,
  cache_write_price_per_mtok: 0,
  context_window: 128000,
  max_output_tokens: 4096,
  input_modalities: ['text'],
  output_modalities: ['text'],
  capabilities: ['streaming'],
  parameter_support: {},
  created_at: now,
  updated_at: now,
  deleted_at: null,
} satisfies Api.ModelOut;

it('treats required route selection as a placeholder instead of a checked option', async () => {
  const user = userEvent.setup();
  let submitted: Api.RuleCreate | undefined;
  render(
    <RuleEditor
      rule={null}
      open
      onOpenChange={() => {}}
      onSubmit={async (payload) => {
        submitted = payload;
      }}
      pending={false}
      catalog={{ providers: [provider], models: [model] }}
    />,
  );

  await user.type(screen.getByLabelText('Rule name'), 'Approved model');
  await user.click(screen.getByRole('combobox', { name: 'Rule action' }));
  await user.click(screen.getByRole('option', { name: 'Allowed models' }));
  const routes = screen.getByRole('button', { name: 'Allowed routes' });
  expect(routes).toHaveTextContent('Choose routes');

  await user.click(routes);
  expect(screen.queryByRole('menuitemcheckbox', { name: 'Choose routes' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('menuitemcheckbox', { name: model.name }));
  await user.keyboard('{Escape}');
  await user.click(screen.getByRole('button', { name: 'Save rule' }));

  await waitFor(() =>
    expect(submitted).toMatchObject({
      name: 'Approved model',
      definition: { action: { kind: 'models', names: [model.name] } },
    }),
  );
});
