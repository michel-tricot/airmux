const ORG_KEY = 'airllm_org'

let currentOrg: string | null = localStorage.getItem(ORG_KEY)

export function getCurrentOrg(): string | null {
  return currentOrg
}

export function setCurrentOrg(org: string | null): void {
  currentOrg = org
  if (org) localStorage.setItem(ORG_KEY, org)
  else localStorage.removeItem(ORG_KEY)
}

export class ApiError extends Error {
  status: number

  constructor(status: number) {
    super(
      status === 401
        ? 'session expired, log in again'
        : status === 403
          ? 'forbidden: this view needs org access or admin rights'
          : `request failed with status ${status}`,
    )
    this.status = status
  }
}

function authHeaders(path: string): Record<string, string> {
  const headers: Record<string, string> = { 'content-type': 'application/json', 'X-Requested-With': 'fetch' }
  if (currentOrg && !path.startsWith('/v1/instance/') && !path.startsWith('/v1/auth/') && !path.startsWith('/v1/orgs')) headers['X-Org-Id'] = currentOrg
  return headers
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      ...authHeaders(path),
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
  user_id: string
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

export interface Me {
  user_id: string
  email: string
  name: string
  instance_admin: boolean
  orgs: string[]
}

export async function fetchMe(): Promise<Me | null> {
  const res = await fetch('/v1/auth/me', { headers: { 'X-Requested-With': 'fetch' } })
  if (res.status === 401 || res.status === 403) return null
  if (!res.ok) throw new ApiError(res.status)
  const body = (await res.json()) as { data: Me }
  return body.data
}

export const login = (body: { email: string; password: string }) => api<Me>('/v1/auth/login', { method: 'POST', body: JSON.stringify(body) })

export const signup = (body: { email: string; name: string; password: string }) =>
  api<Me>('/v1/auth/signup', { method: 'POST', body: JSON.stringify(body) })

export const logout = () => api<{ id: string }>('/v1/auth/logout', { method: 'POST' })

export const listOrgs = () => api<Org[]>('/v1/orgs')
export const listKeys = () => api<ApiKey[]>('/v1/org/keys')
export const getTaxonomy = () => api<Taxonomy>('/v1/taxonomy')
export const listBundles = () => api<Bundle[]>('/v1/org/bundles')
export const listEvents = (limit = 100) => api<UsageEvent[]>(`/v1/org/events?limit=${limit}`)
export const listInstances = (includeOffline = true) => api<Instance[]>(`/v1/org/instances?include_offline=${includeOffline}`)

export const createOrg = (body: { id: string; name: string }) => api<{ id: string }>('/v1/orgs', { method: 'POST', body: JSON.stringify(body) })

export const createKey = () => api<{ key_id: string; token: string }>('/v1/org/keys', { method: 'POST' })

export const revokeKey = (keyId: string) => api<{ key_id: string; status: string }>(`/v1/org/keys/${keyId}`, { method: 'DELETE' })

export const compileBundle = () =>
  api<{ bundle_id: string; version: number }>('/v1/org/bundles/compile', { method: 'POST', body: JSON.stringify({}) })
