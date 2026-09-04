import type * as Api from '@workspace/api-client-react';
export const now = '2026-01-01T00:00:00Z';
export function taxonomyProvider(id: string, name: string, icon = ''): Api.ProviderOut {
  return {
    id,
    name,
    kind: 'openai_compatible',
    base_url: `https://${name}.example/v1`,
    icon,
    param_aliases: {},
    accepted_params: null,
    params_closed: false,
    created_at: now,
    updated_at: now,
    deleted_at: null,
  };
}
