import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
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
  },
  {
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
    capabilities: ['streaming', 'tools', 'json_schema'],
    created_at: now,
    updated_at: now,
    deleted_at: null,
  },
];

beforeEach(() => {
  window.localStorage.setItem('airllm_org_id', ORG.id);
  server.use(http.get(`/api/v1/orgs/${ORG.id}/taxonomy`, () => HttpResponse.json({ providers, models })));
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
    expect(within(claude!).getByText('anthropic/claude-sonnet-4-5')).toHaveClass('border-border', 'font-mono');
    expect(within(claude!).getByText('streaming')).toHaveClass('rounded-full');
    expect(within(claude!).getByText('tools')).toHaveClass('rounded-full');
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
  });

  it('adds visual hierarchy to the catalog summary, groups, capabilities, and active sort', async () => {
    renderModels();

    const claude = (await screen.findByText('anthropic/claude-sonnet-4-5')).closest('tr');
    const gpt = screen.getByText('openai/gpt-5').closest('tr');
    expect(screen.getByLabelText('2 models')).toBeInTheDocument();
    expect(screen.getByLabelText('2 providers')).toBeInTheDocument();
    expect(screen.getByLabelText('2 tool-capable models')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Catalog' })).toHaveAttribute('colspan', '2');
    expect(screen.getByRole('columnheader', { name: 'Limits' })).toHaveAttribute('colspan', '2');
    expect(screen.getByRole('columnheader', { name: 'Pricing' })).toHaveAttribute('colspan', '4');
    expect(within(claude!).getByText('streaming')).toHaveClass('text-primary');
    expect(within(claude!).getByText('tools')).toHaveClass('text-warning');
    expect(within(gpt!).getByText('input:image')).toHaveClass('text-success');
    expect(screen.getByRole('button', { name: /Sort by Model/i })).toHaveClass('text-primary');
  });

  it('combines search and dropdown filters and sorts numeric columns in both directions', async () => {
    const user = userEvent.setup();
    renderModels();
    await screen.findByText('anthropic/claude-sonnet-4-5');

    expect(modelRows()[0]).toHaveTextContent('anthropic/claude-sonnet-4-5');
    await user.click(screen.getByRole('button', { name: /Sort by Input price/i }));
    expect(modelRows()[0]).toHaveTextContent('openai/gpt-5');
    await user.click(screen.getByRole('button', { name: /Sort by Input price/i }));
    expect(modelRows()[0]).toHaveTextContent('anthropic/claude-sonnet-4-5');

    await user.click(screen.getByRole('combobox', { name: 'Filter by provider' }));
    await user.click(await screen.findByRole('option', { name: 'openai' }));
    expect(screen.getByText('openai/gpt-5')).toBeInTheDocument();
    expect(screen.queryByText('anthropic/claude-sonnet-4-5')).not.toBeInTheDocument();
    expect(screen.getByText('1 of 2 models')).toBeInTheDocument();

    await user.click(screen.getByRole('combobox', { name: 'Filter by provider' }));
    await user.click(await screen.findByRole('option', { name: 'All providers' }));
    await user.click(screen.getByRole('combobox', { name: 'Filter by capability' }));
    await user.click(await screen.findByRole('option', { name: 'json_schema' }));
    expect(screen.getByText('openai/gpt-5')).toBeInTheDocument();
    expect(screen.queryByText('anthropic/claude-sonnet-4-5')).not.toBeInTheDocument();

    await user.type(screen.getByRole('textbox', { name: 'Filter models' }), 'not-a-model');
    expect(screen.getByText('No models match these filters.')).toBeInTheDocument();
  });
});
