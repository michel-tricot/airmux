import type * as Api from '@workspace/api-client-react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { createQueryClient } from '@/App';
import {
  useInstanceAccessKeys,
  useUpdateAccessKeyPermissionsMutation,
  useOrgAccessKeys,
  useCreateInstanceAccessKeyMutation,
  useCreateInferenceKeyMutation,
  useInferenceKeys,
  useRevokeOrgAccessKeyMutation,
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

function accessKey(id: string, revokedAt: string | null = null): Api.AccessKeyOut {
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
    scope: { level: 'org', org_id: ORG.id, workspace_id: null },
    status: revokedAt ? 'revoked' : 'active',
  };
}

const WORKSPACE_REF = 'production';

function inferenceKey(id: string, revoked: boolean): Api.InferenceKeyOut {
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
      http.get(`/api/v1/orgs/${ORG.id}/access-keys`, () => HttpResponse.json<{ data: Api.AccessKeyOut[] }>({ data: [key] })),
      http.delete('/api/v1/access-keys/:keyId', () => {
        key = accessKey('ak-1', now);
        return HttpResponse.json<{ data: Api.AccessKeyRevokedOut }>({ data: { id: 'ak-1', status: 'revoked', revoked_at: now } });
      }),
    );

    const list = renderHook(() => useOrgAccessKeys(ORG.id), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    expect(list.result.current.data).toEqual([expect.objectContaining({ revoked_at: null })]);

    const revoke = renderHook(() => useRevokeOrgAccessKeyMutation(ORG.id), { wrapper });
    await revoke.result.current.mutateAsync({ keyId: 'ak-1' });

    await waitFor(() => expect(list.result.current.data).toEqual([expect.objectContaining({ revoked_at: now })]));
  });

  it('minting an access key refetches the access-key list', async () => {
    const keys = [accessKey('ak-1')];
    server.use(
      http.get('/api/v1/instance/access-keys', () => HttpResponse.json<{ data: Api.AccessKeyOut[] }>({ data: keys })),
      http.post('/api/v1/instance/access-keys', () => {
        keys.push(accessKey('ak-2'));
        return HttpResponse.json<{ data: Api.AccessKeyMintedOut }>({ data: { ...accessKey('ak-2'), token: 'tok-once' } });
      }),
    );

    const list = renderHook(() => useInstanceAccessKeys(), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    expect(list.result.current.data).toHaveLength(1);

    const mint = renderHook(() => useCreateInstanceAccessKeyMutation(), { wrapper });
    await mint.result.current.mutateAsync({ data: { label: 'ci', permissions: ['workspaces.read'] } });

    await waitFor(() => expect(list.result.current.data).toHaveLength(2));
  });

  it('minting an inference key refetches the workspace inference key list', async () => {
    const keys = [inferenceKey('ifk-1', false)];
    server.use(
      http.get(`/api/v1/orgs/${ORG.id}/workspaces/${WORKSPACE_REF}/inference-keys`, () =>
        HttpResponse.json<{ data: Api.InferenceKeyOut[] }>({ data: keys }),
      ),
      http.post(`/api/v1/orgs/${ORG.id}/workspaces/${WORKSPACE_REF}/inference-keys`, () => {
        keys.push(inferenceKey('ifk-2', false));
        return HttpResponse.json<{ data: Api.InferenceKeyMintedOut }>({ data: { id: 'ifk-2', token: 'tok-once' } });
      }),
    );

    const list = renderHook(() => useInferenceKeys(ORG.id, WORKSPACE_REF), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    expect(list.result.current.data).toHaveLength(1);

    const mint = renderHook(() => useCreateInferenceKeyMutation(ORG.id, WORKSPACE_REF), { wrapper });
    await mint.result.current.mutateAsync({ orgId: ORG.id, workspaceRef: WORKSPACE_REF, data: { label: 'app' } });

    await waitFor(() => expect(list.result.current.data).toHaveLength(2));
  });

  it('revoking an inference key refetches the workspace inference key list with fresh status', async () => {
    let revoked = false;
    server.use(
      http.get(`/api/v1/orgs/${ORG.id}/workspaces/${WORKSPACE_REF}/inference-keys`, () =>
        HttpResponse.json<{ data: Api.InferenceKeyOut[] }>({ data: [inferenceKey('ifk-1', revoked)] }),
      ),
      http.delete(`/api/v1/orgs/${ORG.id}/workspaces/${WORKSPACE_REF}/inference-keys/:keyId`, () => {
        revoked = true;
        return HttpResponse.json<{ data: Api.InferenceKeyRevokedOut }>({ data: { id: 'ifk-1', status: 'revoked' } });
      }),
    );

    const list = renderHook(() => useInferenceKeys(ORG.id, WORKSPACE_REF), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    expect(list.result.current.data).toEqual([expect.objectContaining({ revoked: false })]);

    const revoke = renderHook(() => useRevokeInferenceKeyMutation(ORG.id, WORKSPACE_REF), { wrapper });
    await revoke.result.current.mutateAsync({ orgId: ORG.id, workspaceRef: WORKSPACE_REF, keyId: 'ifk-1' });

    await waitFor(() => expect(list.result.current.data).toEqual([expect.objectContaining({ revoked: true })]));
  });
});

it('refreshes filtered instance and organization key lists after editing permissions', async () => {
  let key = accessKey('editable');
  server.use(
    http.get('/api/v1/instance/access-keys', () => HttpResponse.json({ data: [key] })),
    http.get(`/api/v1/orgs/${ORG.id}/access-keys`, () => HttpResponse.json({ data: [key] })),
    http.put('/api/v1/access-keys/:keyId/permissions', () => {
      key = { ...key, permissions: ['usage.read'] };
      return HttpResponse.json({ data: key });
    }),
  );
  const instance = renderHook(() => useInstanceAccessKeys({ user_id: key.user_id }), { wrapper });
  const org = renderHook(() => useOrgAccessKeys(ORG.id, { user_id: key.user_id }), { wrapper });
  const update = renderHook(() => useUpdateAccessKeyPermissionsMutation(), { wrapper });
  await waitFor(() => expect(instance.result.current.data?.[0].permissions).toEqual(['workspaces.read']));
  await waitFor(() => expect(org.result.current.data?.[0].permissions).toEqual(['workspaces.read']));
  await update.result.current.mutateAsync({ keyId: key.id, data: { permissions: ['usage.read'] } });
  await waitFor(() => expect(instance.result.current.data?.[0].permissions).toEqual(['usage.read']));
  await waitFor(() => expect(org.result.current.data?.[0].permissions).toEqual(['usage.read']));
});
