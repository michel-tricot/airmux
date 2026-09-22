import { describe, expect, it } from 'vitest';
import { getExportOrgGatewayRequestsUrl, getListOrgGatewayRequestsUrl } from '../src/generated/api';

const repeatedFilters = {
  range: '7d' as const,
  timezone: 'UTC',
  workspace: ['workspace-a', 'workspace-b'],
  principal: ['principal-a', 'principal-b'],
  inference_key: ['key-a', 'key-b'],
  model: ['model-a', 'model-b'],
  provider: ['provider-a', 'provider-b'],
  outcome: ['succeeded', 'pending'] as const,
  confidence: ['provider', 'partial'] as const,
};

describe('request report client', () => {
  it.each([getListOrgGatewayRequestsUrl, getExportOrgGatewayRequestsUrl])('serializes repeated request filters for %p', (urlOf) => {
    const url = new URL(urlOf('org-1', repeatedFilters), 'https://control.example');

    expect(url.searchParams.getAll('workspace')).toEqual(['workspace-a', 'workspace-b']);
    expect(url.searchParams.getAll('principal')).toEqual(['principal-a', 'principal-b']);
    expect(url.searchParams.getAll('inference_key')).toEqual(['key-a', 'key-b']);
    expect(url.searchParams.getAll('model')).toEqual(['model-a', 'model-b']);
    expect(url.searchParams.getAll('provider')).toEqual(['provider-a', 'provider-b']);
    expect(url.searchParams.getAll('outcome')).toEqual(['succeeded', 'pending']);
    expect(url.searchParams.getAll('confidence')).toEqual(['provider', 'partial']);
  });
});
