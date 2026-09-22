import { describe, expect, it } from 'vitest';
import { getGetOrgOverviewReportUrl } from '../src/generated/api';

describe('overview report client', () => {
  it('serializes repeated filters as repeated query parameters', () => {
    const url = new URL(
      getGetOrgOverviewReportUrl('org-1', {
        range: '7d',
        timezone: 'UTC',
        model: ['model-a', 'model-b'],
        provider: ['provider-a', 'provider-b'],
        group: 'provider_credential',
      }),
      'https://control.example',
    );

    expect(url.searchParams.getAll('model')).toEqual(['model-a', 'model-b']);
    expect(url.searchParams.getAll('provider')).toEqual(['provider-a', 'provider-b']);
    expect(url.searchParams.get('group')).toBe('provider_credential');
  });
});
