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
    super(status === 401 ? 'unauthorized: check the admin token' : `request failed with status ${status}`)
    this.status = status
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/admin${path}`, {
    ...init,
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${getToken() ?? ''}`,
      ...init?.headers,
    },
  })
  if (!res.ok) throw new ApiError(res.status)
  return res.json() as Promise<T>
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
  org_id: string
  kind: string
  base_url: string
  credential_ref: string
  cache_read_multiplier: number
  cache_write_multiplier: number
}

export interface Model {
  id: string
  org_id: string
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

export const listOrgs = () => api<Org[]>('/orgs')
export const listKeys = () => api<ApiKey[]>('/keys')
export const listProviders = () => api<Provider[]>('/providers')
export const listModels = () => api<Model[]>('/models')
export const listBundles = () => api<Bundle[]>('/bundles')
export const listEvents = (limit = 100) => api<UsageEvent[]>(`/events?limit=${limit}`)
export const listInstances = (includeOffline = true) => api<Instance[]>(`/instances?include_offline=${includeOffline}`)

export const createOrg = (body: { id: string; name: string }) => api<{ id: string }>('/orgs', { method: 'POST', body: JSON.stringify(body) })

export const createKey = (body: { org_id: string; allowed_models: string[] }) =>
  api<{ key_id: string; token: string }>('/keys', { method: 'POST', body: JSON.stringify(body) })

export const revokeKey = (keyId: string) => api<{ key_id: string; status: string }>(`/keys/${keyId}`, { method: 'DELETE' })

export const compileBundle = (orgId: string) =>
  api<{ bundle_id: string; version: number }>('/bundles/compile', { method: 'POST', body: JSON.stringify({ org_id: orgId }) })
