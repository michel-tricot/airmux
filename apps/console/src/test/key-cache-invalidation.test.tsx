import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { createQueryClient } from '@/App';
import {
  useAccessKeys,
  useCreateAccessKeyMutation,
  useCreateInferenceKeyMutation,
  useInferenceKeys,
  useRevokeAccessKeyMutation,
  useRevokeInferenceKeyMutation,
} from '@/features/keys/hooks';
import { ORG, server } from './msw';

const now = '2026-01-01T00:00:00Z';
let queryClient: QueryClient;

beforeEach(() => {
  queryClient = createQueryClient();
});

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

function accessKey(id: string, revokedAt: string | null = null) {
  return {
    id,
    user_id: 'user-1',
    org_id: ORG.id,
    workspace_id: null,
    parent_id: null,
    prefix: 'sk-cp-abc',
    permissions: ['workspaces.read'],
    label: 'ci',
    expires_at: null,
    revoked_at: revokedAt,
    created_at: now,
    updated_at: now,
    deleted_at: null,
    boundary: 'org',
    status: revokedAt ? 'revoked' : 'active',
  };
}

const WORKSPACE_REF = 'production';

function inferenceKey(id: string, revoked: boolean) {
  return {
    id,
    org_id: ORG.id,
    workspace_id: 'ws-1',
    user_id: 'user-1',
    revoked,
    label: 'app',
    prefix: 'llm_abc',
    created_at: now,
    updated_at: now,
    deleted_at: null,
  };
}

describe('key cache invalidation across pages', () => {
  it('revoking an access key refreshes a filtered access-key list', async () => {
    let key = accessKey('ak-1');
    server.use(
      http.get('/v1/access-keys', () => HttpResponse.json([key])),
      http.delete('/v1/access-keys/:keyId', () => {
        key = accessKey('ak-1', now);
        return HttpResponse.json({ id: 'ak-1', status: 'revoked', revoked_at: now });
      }),
    );

    const list = renderHook(() => useAccessKeys({ org_id: ORG.id }), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    expect(list.result.current.data).toEqual([expect.objectContaining({ revoked_at: null })]);

    const revoke = renderHook(() => useRevokeAccessKeyMutation(), { wrapper });
    await revoke.result.current.mutateAsync({ keyId: 'ak-1' });

    await waitFor(() => expect(list.result.current.data).toEqual([expect.objectContaining({ revoked_at: now })]));
  });

  it('minting an access key refetches the access-key list', async () => {
    const keys = [accessKey('ak-1')];
    server.use(
      http.get('/v1/access-keys', () => HttpResponse.json(keys)),
      http.post('/v1/access-keys', () => {
        keys.push(accessKey('ak-2'));
        return HttpResponse.json({ ...accessKey('ak-2'), token: 'tok-once' });
      }),
    );

    const list = renderHook(() => useAccessKeys(), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    expect(list.result.current.data).toHaveLength(1);

    const mint = renderHook(() => useCreateAccessKeyMutation(), { wrapper });
    await mint.result.current.mutateAsync({ data: { label: 'ci', permissions: ['workspaces.read'] } });

    await waitFor(() => expect(list.result.current.data).toHaveLength(2));
  });

  it('minting an inference key refetches the workspace inference key list', async () => {
    const keys = [inferenceKey('ifk-1', false)];
    server.use(
      http.get(`/v1/org/workspaces/${WORKSPACE_REF}/inference-keys`, () => HttpResponse.json(keys)),
      http.post(`/v1/org/workspaces/${WORKSPACE_REF}/inference-keys`, () => {
        keys.push(inferenceKey('ifk-2', false));
        return HttpResponse.json({ id: 'ifk-2', token: 'tok-once' });
      }),
    );

    const list = renderHook(() => useInferenceKeys(ORG.id, WORKSPACE_REF), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    expect(list.result.current.data).toHaveLength(1);

    const mint = renderHook(() => useCreateInferenceKeyMutation(ORG.id, WORKSPACE_REF), { wrapper });
    await mint.result.current.mutateAsync({ workspaceRef: WORKSPACE_REF, data: { label: 'app' } });

    await waitFor(() => expect(list.result.current.data).toHaveLength(2));
  });

  it('revoking an inference key refetches the workspace inference key list with fresh status', async () => {
    let revoked = false;
    server.use(
      http.get(`/v1/org/workspaces/${WORKSPACE_REF}/inference-keys`, () => HttpResponse.json([inferenceKey('ifk-1', revoked)])),
      http.delete(`/v1/org/workspaces/${WORKSPACE_REF}/inference-keys/:keyId`, () => {
        revoked = true;
        return HttpResponse.json({ id: 'ifk-1', status: 'revoked' });
      }),
    );

    const list = renderHook(() => useInferenceKeys(ORG.id, WORKSPACE_REF), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    expect(list.result.current.data).toEqual([expect.objectContaining({ revoked: false })]);

    const revoke = renderHook(() => useRevokeInferenceKeyMutation(ORG.id, WORKSPACE_REF), { wrapper });
    await revoke.result.current.mutateAsync({ workspaceRef: WORKSPACE_REF, keyId: 'ifk-1' });

    await waitFor(() => expect(list.result.current.data).toEqual([expect.objectContaining({ revoked: true })]));
  });
});
