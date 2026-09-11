import type * as Api from '@workspace/api-client-react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { RuleEditor } from '@/pages/app/workspace/RuleEditor';
import { now, taxonomyProvider } from './fixtures';

const provider = taxonomyProvider('provider-1', 'openai', '<svg viewBox="0 0 16 16"><path d="M1 1h14v14H1z" /></svg>');
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
const secondModel = { ...model, id: 'model-2', name: 'openai/o3' } satisfies Api.ModelOut;

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
  expect(screen.queryByRole('option', { name: 'Choose routes' })).not.toBeInTheDocument();
  const modelOption = screen.getByRole('option', { name: `${model.name}, ${provider.name}` });
  expect(modelOption.querySelector('svg')).toBeInTheDocument();
  await user.click(modelOption);
  await user.click(screen.getByRole('button', { name: 'Done' }));
  await user.click(screen.getByRole('button', { name: 'Save rule' }));

  await waitFor(() =>
    expect(submitted).toMatchObject({
      name: 'Approved model',
      definition: { action: { kind: 'models', names: [model.name] } },
    }),
  );
});

it('shows provider icons in provider rule choices', async () => {
  const user = userEvent.setup();
  render(
    <RuleEditor
      rule={null}
      open
      onOpenChange={() => {}}
      onSubmit={async () => {}}
      pending={false}
      catalog={{ providers: [provider], models: [model] }}
    />,
  );

  await user.click(screen.getByRole('combobox', { name: 'Rule action' }));
  await user.click(screen.getByRole('option', { name: 'Allowed providers' }));
  await user.click(screen.getByRole('button', { name: 'Allowed routes' }));

  expect(screen.getByRole('menuitemcheckbox', { name: provider.name }).querySelector('svg')).toBeInTheDocument();
});

it('names a single selected backup model in the picker summary', async () => {
  const user = userEvent.setup();
  render(
    <RuleEditor
      rule={null}
      open
      onOpenChange={() => {}}
      onSubmit={async () => {}}
      pending={false}
      catalog={{ providers: [provider], models: [model] }}
    />,
  );

  await user.click(screen.getByRole('combobox', { name: 'Rule action' }));
  await user.click(screen.getByRole('option', { name: 'Model fallbacks' }));
  const routes = screen.getByRole('button', { name: 'Allowed routes' });
  await user.click(routes);
  await user.click(screen.getByRole('option', { name: `${model.name}, ${provider.name}` }));
  await user.click(screen.getByRole('button', { name: 'Done' }));

  expect(routes).toHaveTextContent(model.name);
  expect(routes).not.toHaveTextContent('(1)');
});

it('does not validate fields from an inactive action', async () => {
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
  await user.click(screen.getByRole('option', { name: 'Request limits' }));
  await user.clear(screen.getByLabelText('Maximum requested output tokens'));
  await user.click(screen.getByRole('combobox', { name: 'Rule action' }));
  await user.click(screen.getByRole('option', { name: 'Allowed models' }));
  await user.click(screen.getByRole('button', { name: 'Allowed routes' }));
  await user.click(screen.getByRole('option', { name: `${model.name}, ${provider.name}` }));
  await user.click(screen.getByRole('button', { name: 'Done' }));
  await user.click(screen.getByRole('button', { name: 'Save rule' }));

  await waitFor(() => expect(submitted?.definition.action).toEqual({ kind: 'models', names: [model.name] }));
});

it('searches large model choices by model or provider name', async () => {
  const user = userEvent.setup();
  render(
    <RuleEditor
      rule={null}
      open
      onOpenChange={() => {}}
      onSubmit={async () => {}}
      pending={false}
      catalog={{ providers: [provider], models: [model, secondModel] }}
    />,
  );

  await user.click(screen.getByRole('combobox', { name: 'Rule action' }));
  await user.click(screen.getByRole('option', { name: 'Allowed models' }));
  await user.click(screen.getByRole('button', { name: 'Allowed routes' }));
  await user.type(screen.getByRole('searchbox', { name: 'Search allowed routes' }), 'gpt-test');

  expect(screen.getByRole('option', { name: `${model.name}, ${provider.name}` })).toBeVisible();
  expect(screen.queryByRole('option', { name: `${secondModel.name}, ${provider.name}` })).not.toBeInTheDocument();
});
