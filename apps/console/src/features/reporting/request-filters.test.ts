import { describe, expect, it } from 'vitest';
import type { OverviewFilters } from './filters';
import { orgRequestParams, overviewRequestsHref, parseRequestFilters, setRequestFilter, workspaceRequestParams } from './request-filters';

describe('request report URL filters', () => {
  it('parses strict controls and repeated request filters', () => {
    const filters = parseRequestFilters(
      new URLSearchParams(
        'range=custom&timezone=UTC&start_date=2026-09-01&end_date=2026-09-22&workspace=ws-1&principal=user-1' +
          '&inference_key=key-1&model=model-1&provider=openai&provider_credential=credential-1&provider_credential=unattributed' +
          '&outcome=succeeded&outcome=pending&confidence=provider&confidence=partial&search=100%25_literal&sort=known_cost_usd&direction=asc&as_of=snapshot-1',
      ),
      'America/Los_Angeles',
    );

    expect(filters).toMatchObject({
      range: 'custom',
      timezone: 'UTC',
      startDate: '2026-09-01',
      endDate: '2026-09-22',
      workspace: ['ws-1'],
      principal: ['user-1'],
      inferenceKey: ['key-1'],
      model: ['model-1'],
      provider: ['openai'],
      providerCredential: ['credential-1', 'unattributed'],
      outcome: ['succeeded', 'pending'],
      confidence: ['provider', 'partial'],
      search: '100%_literal',
      sort: 'known_cost_usd',
      direction: 'asc',
      asOf: 'snapshot-1',
    });
  });

  it('uses generated request shapes and discards workspace scope where invalid', () => {
    const filters = parseRequestFilters(new URLSearchParams('workspace=ws-1&provider_credential=unattributed&outcome=denied'), 'UTC');

    expect(orgRequestParams(filters)).toMatchObject({ workspace: ['ws-1'], provider_credential: ['unattributed'], outcome: ['denied'] });
    expect(workspaceRequestParams(filters)).not.toHaveProperty('workspace');
  });

  it('keeps the report snapshot while resetting custom dates when filters change', () => {
    const current = new URLSearchParams('range=custom&start_date=2026-09-01&end_date=2026-09-22&as_of=snapshot-1');
    const next = setRequestFilter(current, 'range', '30d');

    expect(next.has('start_date')).toBe(false);
    expect(next.has('end_date')).toBe(false);
    expect(next.get('as_of')).toBe('snapshot-1');
  });

  it('builds normalized total and provider credential drilldowns without presentation filters', () => {
    const overview: OverviewFilters = {
      range: '7d',
      timezone: 'UTC',
      startDate: '',
      endDate: '',
      bucket: 'hour',
      split: 'model',
      group: 'provider_credential',
      workspace: ['ws-1'],
      principal: ['user-1'],
      inferenceKey: [],
      model: ['model-1'],
      provider: [],
    };

    const total = new URL(overviewRequestsHref('/org/requests', overview, 'snapshot-1'), 'http://console.test');
    expect(total.searchParams.get('range')).toBe('7d');
    expect(total.searchParams.getAll('workspace')).toEqual(['ws-1']);
    expect(total.searchParams.get('as_of')).toBe('snapshot-1');
    expect(total.searchParams.has('bucket')).toBe(false);
    expect(total.searchParams.has('split')).toBe(false);
    expect(total.searchParams.has('group')).toBe(false);

    const row = new URL(
      overviewRequestsHref('/org/requests', overview, 'snapshot-1', { group: 'provider_credential', id: null }),
      'http://console.test',
    );
    expect(row.searchParams.getAll('provider_credential')).toEqual(['unattributed']);
  });

  it('does not add a workspace filter to workspace request drilldowns', () => {
    const overview = {
      ...parseRequestFilters(new URLSearchParams('workspace=ws-other'), 'UTC'),
      bucket: 'day' as const,
      split: 'none' as const,
      group: 'workspace' as const,
    };
    const href = new URL(
      overviewRequestsHref('/org/workspaces/production/requests', overview, 'snapshot-1', undefined, 'workspace'),
      'http://console.test',
    );

    expect(href.searchParams.has('workspace')).toBe(false);
  });
});
