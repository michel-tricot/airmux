import { describe, expect, it } from 'vitest';
import { orgOverviewParams, parseOverviewFilters, setOverviewFilter, workspaceOverviewParams } from './filters';

describe('overview report URL filters', () => {
  it('parses closed controls and bounded repeated filters', () => {
    const search = new URLSearchParams(
      'range=custom&timezone=America%2FLos_Angeles&start_date=2026-09-01&end_date=2026-09-22&bucket=hour&split=provider&group=principal' +
        '&workspace=ws-1&workspace=ws-2&principal=user-1&inference_key=key-1&model=model-1&model=model-2&provider=openai',
    );

    expect(parseOverviewFilters(search, 'UTC')).toEqual({
      range: 'custom',
      timezone: 'America/Los_Angeles',
      startDate: '2026-09-01',
      endDate: '2026-09-22',
      bucket: 'hour',
      split: 'provider',
      group: 'principal',
      workspace: ['ws-1', 'ws-2'],
      principal: ['user-1'],
      inferenceKey: ['key-1'],
      model: ['model-1', 'model-2'],
      provider: ['openai'],
    });
  });

  it('serializes arrays as repeated values and drops invalid closed controls', () => {
    const current = new URLSearchParams('range=invalid&bucket=week&split=bad&group=bad');
    const withModels = setOverviewFilter(current, 'model', ['gpt-4o', 'claude']);
    const withProviders = setOverviewFilter(withModels, 'provider', ['openai', 'anthropic']);
    const filters = parseOverviewFilters(withProviders, 'UTC');

    expect(withProviders.getAll('model')).toEqual(['gpt-4o', 'claude']);
    expect(withProviders.getAll('provider')).toEqual(['openai', 'anthropic']);
    expect(filters.range).toBe('7d');
    expect(filters.bucket).toBe('day');
    expect(filters.split).toBe('none');
    expect(filters.group).toBe('workspace');
  });

  it('accepts provider credential attribution grouping', () => {
    const filters = parseOverviewFilters(new URLSearchParams('group=provider_credential'), 'UTC');

    expect(filters.group).toBe('provider_credential');
    expect(orgOverviewParams(filters).group).toBe('provider_credential');
  });

  it('caps repeated identity filters at the API limit', () => {
    const search = new URLSearchParams();
    for (let index = 0; index < 60; index += 1) search.append('model', `model-${index}`);
    const filters = parseOverviewFilters(search, 'UTC');

    expect(filters.model).toHaveLength(50);
    expect(filters.model.at(-1)).toBe('model-49');
  });

  it('normalizes invalid timezones and incomplete custom dates before requesting', () => {
    const filters = parseOverviewFilters(new URLSearchParams('range=custom&timezone=Neverland&start_date=invalid'), 'UTC');

    expect(filters.timezone).toBe('UTC');
    expect(filters.startDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(filters.endDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('maps repeated filters to each generated request shape', () => {
    const filters = parseOverviewFilters(
      new URLSearchParams('workspace=ws-1&principal=user-1&inference_key=key-1&model=model-1&provider=openai'),
      'UTC',
    );

    expect(orgOverviewParams(filters)).toMatchObject({
      workspace: ['ws-1'],
      principal: ['user-1'],
      inference_key: ['key-1'],
      model: ['model-1'],
      provider: ['openai'],
    });
    expect(workspaceOverviewParams(filters)).not.toHaveProperty('workspace');
  });

  it('removes custom dates when switching to a preset', () => {
    const search = new URLSearchParams('range=custom&start_date=2026-09-01&end_date=2026-09-22');
    const next = setOverviewFilter(search, 'range', '30d');

    expect(next.has('start_date')).toBe(false);
    expect(next.has('end_date')).toBe(false);
  });
});
