import type * as Api from '@workspace/api-client-react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import App from '@/App';
import { ORG, server } from './msw';

const now = '2026-01-01T00:00:00Z';
const providers = [
  {
    id: 'provider-anthropic',
    name: 'anthropic',
    kind: 'anthropic',
    base_url: 'https://api.anthropic.com',
    icon: '',
    param_aliases: {},
    accepted_params: null,
    params_closed: false,
    created_at: now,
    updated_at: now,
    deleted_at: null,
  },
  {
    id: 'provider-openai',
    name: 'openai',
    kind: 'openai_compatible',
    base_url: 'https://api.openai.com/v1',
    icon: '',
    param_aliases: {},
    accepted_params: null,
    params_closed: false,
    created_at: now,
    updated_at: now,
    deleted_at: null,
  },
];
const models = [
  {
    egress_kind: null,
    parameter_support: {},
    id: 'model-claude',
    name: 'anthropic/claude-sonnet-4-5',
    provider_id: providers[0].id,
    upstream_model: 'claude-sonnet-4-5-20250929',
    input_price_per_mtok: 3,
    output_price_per_mtok: 15,
    cache_read_price_per_mtok: 0.3,
    cache_write_price_per_mtok: 3.75,
    context_window: 200000,
    max_output_tokens: 64000,
    input_modalities: ['text'],
    output_modalities: ['text'],
    capabilities: ['streaming', 'tools'],
    created_at: now,
    updated_at: now,
    deleted_at: null,
  } satisfies Api.ModelOut,
  {
    egress_kind: null,
    parameter_support: {},
    id: 'model-gpt',
    name: 'openai/gpt-5',
    provider_id: providers[1].id,
    upstream_model: 'gpt-5-2025-08-07',
    input_price_per_mtok: 1.25,
    output_price_per_mtok: 10,
    cache_read_price_per_mtok: 0.125,
    cache_write_price_per_mtok: 1.25,
    context_window: 400000,
    max_output_tokens: 128000,
    input_modalities: ['text', 'image'],
    output_modalities: ['text'],
    capabilities: ['streaming', 'tools', 'structured_output', 'reasoning'],
    created_at: now,
    updated_at: now,
    deleted_at: null,
  } satisfies Api.ModelOut,
];

beforeEach(() => {
  window.localStorage.setItem('airllm_org_id', ORG.id);
  server.use(
    http.get(`/api/v1/organizations/${ORG.id}/taxonomy`, () => HttpResponse.json<{ data: Api.TaxonomyOut }>({ data: { providers, models } })),
  );
});

function renderModels() {
  window.history.replaceState(null, '', '/org/models');
  return render(<App />);
}

function modelRows() {
  return within(screen.getByRole('table'))
    .getAllByRole('row')
    .filter((row) => row.parentElement?.tagName === 'TBODY');
}

describe('organization models', () => {
  it('lists every model and price with sortable columns', async () => {
    renderModels();

    expect(await screen.findByRole('heading', { level: 1, name: 'Models' })).toBeInTheDocument();
    const claude = (await screen.findByText('anthropic/claude-sonnet-4-5')).closest('tr');
    expect(claude).not.toBeNull();
    expect(claude).toHaveTextContent('anthropic');
    expect(claude).not.toHaveTextContent('claude-sonnet-4-5-20250929');
    const modelCell = within(claude!).getByText('anthropic/claude-sonnet-4-5').closest('td');
    expect(modelCell).not.toBeNull();
    expect(within(modelCell!).getByText('anthropic/claude-sonnet-4-5')).toHaveAttribute('tabindex', '0');
    expect(within(modelCell!).queryByRole('button', { name: 'Show model metadata' })).not.toBeInTheDocument();
    expect(within(modelCell!).queryByText('streaming')).not.toBeInTheDocument();
    expect(claude).toHaveTextContent('$3.00');
    expect(claude).toHaveTextContent('$15.00');
    expect(claude).toHaveTextContent('$0.30');
    expect(claude).toHaveTextContent('$3.75');

    for (const label of [
      'Model',
      'Provider',
      'Context window',
      'Max output',
      'Input price',
      'Output price',
      'Cache read price',
      'Cache write price',
    ]) {
      expect(screen.getByRole('button', { name: new RegExp(`Sort by ${label}`, 'i') })).toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeDisabled();
  });

  it('summarizes the catalog and labels its column groups', async () => {
    renderModels();

    await screen.findByText('anthropic/claude-sonnet-4-5');
    expect(screen.getByLabelText('2 models')).toBeInTheDocument();
    expect(screen.getByLabelText('2 providers')).toBeInTheDocument();
    expect(screen.getByLabelText('2 tool-capable models')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Catalog' })).toHaveAttribute('colspan', '2');
    expect(screen.getByRole('columnheader', { name: 'Limits' })).toHaveAttribute('colspan', '2');
    expect(screen.getByRole('columnheader', { name: 'Pricing' })).toHaveAttribute('colspan', '4');
  });

  it('combines search and multi-select filters and sorts numeric columns in both directions', async () => {
    const user = userEvent.setup();
    renderModels();
    await screen.findByText('anthropic/claude-sonnet-4-5');

    expect(modelRows()[0]).toHaveTextContent('anthropic/claude-sonnet-4-5');
    await user.click(screen.getByRole('button', { name: /Sort by Input price/i }));
    expect(modelRows()[0]).toHaveTextContent('openai/gpt-5');
    await user.click(screen.getByRole('button', { name: /Sort by Input price/i }));
    expect(modelRows()[0]).toHaveTextContent('anthropic/claude-sonnet-4-5');

    await user.click(screen.getByRole('button', { name: 'Filter by provider' }));
    await user.click(await screen.findByRole('menuitemcheckbox', { name: 'openai' }));
    expect(screen.getByText('openai/gpt-5')).toBeInTheDocument();
    expect(screen.queryByText('anthropic/claude-sonnet-4-5')).not.toBeInTheDocument();
    expect(screen.getByText('1 of 2 models')).toBeInTheDocument();
    await user.click(screen.getByRole('menuitemcheckbox', { name: 'anthropic' }));
    expect(screen.getByText('anthropic/claude-sonnet-4-5')).toBeInTheDocument();
    expect(screen.getByText('2 of 2 models')).toBeInTheDocument();
    await user.click(screen.getByRole('menuitemcheckbox', { name: 'All providers' }));
    await user.keyboard('{Escape}');

    await user.click(screen.getByRole('button', { name: 'Filter by capability' }));
    await user.click(await screen.findByRole('menuitemcheckbox', { name: 'tools' }));
    await user.click(screen.getByRole('menuitemcheckbox', { name: 'reasoning' }));
    expect(screen.getByText('openai/gpt-5')).toBeInTheDocument();
    expect(screen.queryByText('anthropic/claude-sonnet-4-5')).not.toBeInTheDocument();
    await user.click(screen.getByRole('menuitemcheckbox', { name: 'All capabilities' }));
    await user.keyboard('{Escape}');

    await user.click(screen.getByRole('button', { name: 'Filter by modality' }));
    await user.click(await screen.findByRole('menuitemcheckbox', { name: 'Input: text' }));
    expect(screen.getByText('2 of 2 models')).toBeInTheDocument();
    expect(screen.getByText('anthropic/claude-sonnet-4-5')).toBeInTheDocument();
    await user.click(screen.getByRole('menuitemcheckbox', { name: 'Input: image' }));
    expect(screen.getByText('openai/gpt-5')).toBeInTheDocument();
    expect(screen.queryByText('anthropic/claude-sonnet-4-5')).not.toBeInTheDocument();
    await user.keyboard('{Escape}');

    await user.type(screen.getByRole('textbox', { name: 'Filter models' }), 'not-a-model');
    expect(screen.getByText('No models match these filters.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(screen.getByText('anthropic/claude-sonnet-4-5')).toBeInTheDocument();
    expect(screen.getByText('openai/gpt-5')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Filter models' })).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Filter by modality' })).toHaveTextContent('All modalities');
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeDisabled();
  });

  it('shows input to output modality icons below the model name with names on hover', async () => {
    const user = userEvent.setup();
    renderModels();

    const gpt = (await screen.findByText('openai/gpt-5')).closest('tr');
    const modalityFlow = within(gpt!).getByLabelText('Input to output modalities');
    const inputText = within(modalityFlow).getByRole('button', { name: 'Input modality: text' });
    const inputImage = within(modalityFlow).getByRole('button', { name: 'Input modality: image' });
    const outputText = within(modalityFlow).getByRole('button', { name: 'Output modality: text' });
    expect(inputText.querySelector('svg')).toBeInTheDocument();
    expect(inputImage.querySelector('svg')).toBeInTheDocument();
    expect(outputText.querySelector('svg')).toBeInTheDocument();
    expect(modalityFlow.querySelector('.lucide-arrow-right')).toBeInTheDocument();
    expect(within(modalityFlow).queryByRole('button', { name: 'Show model metadata' })).not.toBeInTheDocument();

    await user.hover(inputImage);
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Input: Image');
  });

  it('shows capabilities when the model name is hovered', async () => {
    const user = userEvent.setup();
    renderModels();

    const gpt = (await screen.findByText('openai/gpt-5')).closest('tr');
    const modelName = within(gpt!).getByText('openai/gpt-5');
    expect(modelName).toHaveAttribute('tabindex', '0');
    expect(within(gpt!).queryByRole('button', { name: 'Show model metadata' })).not.toBeInTheDocument();
    expect(within(gpt!).queryByText('streaming')).not.toBeInTheDocument();

    await user.hover(modelName);
    const tooltip = await screen.findByRole('tooltip');
    for (const capability of ['streaming', 'tools', 'structured_output', 'reasoning']) {
      expect(within(tooltip).getByText(capability)).toBeInTheDocument();
    }
    expect(within(tooltip).queryByText('I/O modalities')).not.toBeInTheDocument();
  });

  it('shows the declared text-only modalities without inventing image support', async () => {
    const user = userEvent.setup();
    renderModels();

    const claude = (await screen.findByText('anthropic/claude-sonnet-4-5')).closest('tr');
    const modalityFlow = within(claude!).getByLabelText('Input to output modalities');
    const input = within(modalityFlow).getByRole('button', { name: 'Input modality: text' });
    expect(within(modalityFlow).getByRole('button', { name: 'Output modality: text' })).toBeInTheDocument();
    expect(within(modalityFlow).queryByRole('button', { name: 'Input modality: image' })).not.toBeInTheDocument();
    await user.hover(input);
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Input: Text');
  });
});

it('waits for catalog readiness when the server takes longer than one second', async () => {
  server.use(
    http.get(`/api/v1/organizations/${ORG.id}/taxonomy`, async () => {
      await delay(1200);
      return HttpResponse.json({ data: { providers, models } });
    }),
  );
  renderModels();
  expect(await screen.findByText('anthropic/claude-sonnet-4-5')).toBeVisible();
});
