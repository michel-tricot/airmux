const TOKEN_KEY = 'airllm_admin_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  status: number

  constructor(status: number) {
    super(
      status === 401
        ? 'unauthorized: check the management token'
        : status === 403
          ? 'forbidden: this view needs a different token scope'
          : `request failed with status ${status}`,
    )
    this.status = status
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${getToken() ?? ''}`,
      ...init?.headers,
    },
  })
  if (!res.ok) throw new ApiError(res.status)
  const body = (await res.json()) as { data: T }
  return body.data
}

export interface Org {
  id: string
  name: string
  created_at: string
}

export interface ApiKey {
  id: string
  org_id: string
  allowed_models: string[]
  disabled: boolean
  created_at: string
}

export interface Provider {
  id: string
  kind: string
  base_url: string
  credential_ref: string
  cache_read_multiplier: number
  cache_write_multiplier: number
}

export interface Model {
  id: string
  provider_id: string
  upstream_model: string
  input_price_per_mtok: number
  output_price_per_mtok: number
  context_window: number
  max_output_tokens: number | null
  capabilities: string[]
}

export interface Bundle {
  id: string
  org_id: string
  version: number
  issued_at: string
  expires_at: string
  signing_key_id: string
}

export interface UsageEvent {
  event_id: string
  request_id: string
  occurred_at: string
  org_id: string
  key_id: string
  model_id: string
  provider_id: string
  bundle_id: string
  input_tokens: number
  output_tokens: number
  cost_usd: number
  cost_input_usd: number
  cost_output_usd: number
  cache_read_tokens: number
  cache_write_tokens: number
  latency_ms: number
  status: string
  stream: boolean
}

export interface Instance {
  instance_id: string
  org_id: string | null
  version: string
  bundle_id: string | null
  address: string | null
  status: 'online' | 'offline'
  first_seen: string
  last_seen: string
}

export interface Taxonomy {
  providers: Provider[]
  models: Model[]
}

export const listOrgs = () => api<Org[]>('/v1/instance/orgs')
export const listKeys = () => api<ApiKey[]>('/v1/org/keys')
export const getTaxonomy = () => api<Taxonomy>('/v1/taxonomy')
export const listBundles = () => api<Bundle[]>('/v1/org/bundles')
export const listEvents = (limit = 100) => api<UsageEvent[]>(`/v1/org/events?limit=${limit}`)
export const listInstances = (includeOffline = true) => api<Instance[]>(`/v1/org/instances?include_offline=${includeOffline}`)

export const createOrg = (body: { id: string; name: string }) => api<{ id: string }>('/v1/instance/orgs', { method: 'POST', body: JSON.stringify(body) })

export const createKey = (body: { allowed_models: string[] }) =>
  api<{ key_id: string; token: string }>('/v1/org/keys', { method: 'POST', body: JSON.stringify(body) })

export const revokeKey = (keyId: string) => api<{ key_id: string; status: string }>(`/v1/org/keys/${keyId}`, { method: 'DELETE' })

export const compileBundle = () =>
  api<{ bundle_id: string; version: number }>('/v1/org/bundles/compile', { method: 'POST', body: JSON.stringify({}) })
