import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, ResponseParseError, customFetch, setAuthTokenGetter, setBaseUrl, setDefaultHeaders } from '../src/custom-fetch';

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: { 'content-type': 'application/json', ...init?.headers },
  });
}

async function rejectionOf(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise;
  } catch (error: unknown) {
    return error;
  }
  throw new Error('Expected promise to reject');
}

afterEach(() => {
  setAuthTokenGetter(null);
  setBaseUrl(null);
  setDefaultHeaders(null);
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe('customFetch', () => {
  it.each([{ body: null }, { body: [] }, { body: { id: 'item-1' } }, { body: { data: [], extra: true } }])(
    'rejects a malformed success envelope: $body',
    async ({ body }) => {
      fetchMock.mockResolvedValue(jsonResponse(body));
      vi.stubGlobal('fetch', fetchMock);

      await expect(customFetch('/api/v1/items')).rejects.toThrow('Expected a response envelope containing only data');
    },
  );

  it('unwraps a successful response envelope', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: { id: 'item-1' } }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(customFetch<{ id: string }>('/api/v1/items')).resolves.toEqual({ id: 'item-1' });
  });

  it('preserves error data and request context', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Access denied' }, { status: 403, statusText: 'Forbidden' }));
    vi.stubGlobal('fetch', fetchMock);

    const error = await rejectionOf(customFetch('/api/v1/items', { method: 'POST' }));
    expect(error).toMatchObject({
      name: 'ApiError',
      status: 403,
      method: 'POST',
      url: '/api/v1/items',
      data: { detail: 'Access denied' },
      message: 'HTTP 403 Forbidden: Access denied',
    });
    expect(error).toBeInstanceOf(ApiError);
  });

  it('lets request headers override configured defaults and bearer auth', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ data: null }));
    vi.stubGlobal('fetch', fetchMock);
    setDefaultHeaders(() => ({ 'X-Trace-Id': 'default-trace', 'X-Skip': null }));
    setAuthTokenGetter(() => 'default-token');

    await customFetch('/api/v1/items', {
      headers: { Authorization: 'Bearer explicit-token', 'X-Trace-Id': 'selected-trace' },
    });

    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(headers.get('authorization')).toBe('Bearer explicit-token');
    expect(headers.get('x-trace-id')).toBe('selected-trace');
    expect(headers.has('x-skip')).toBe(false);
  });

  it('returns null without parsing responses that cannot carry a body', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(customFetch('/api/v1/items', { method: 'DELETE' })).resolves.toBeNull();
  });

  it('reports malformed JSON with the raw response', async () => {
    fetchMock.mockResolvedValue(new Response('{broken', { headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    const error = await rejectionOf(customFetch('/api/v1/items'));
    expect(error).toBeInstanceOf(ResponseParseError);
    expect(error).toMatchObject({ rawBody: '{broken', method: 'GET', url: '/api/v1/items' });
  });

  it('applies a configured base URL only to relative API paths', async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ data: [] }));
    vi.stubGlobal('fetch', fetchMock);
    setBaseUrl('https://gateway.example/');

    await customFetch('/api/v1/items');
    await customFetch('https://other.example/v1/items');

    expect(fetchMock.mock.calls[0]?.[0]).toBe('https://gateway.example/api/v1/items');
    expect(fetchMock.mock.calls[1]?.[0]).toBe('https://other.example/v1/items');
  });
});
