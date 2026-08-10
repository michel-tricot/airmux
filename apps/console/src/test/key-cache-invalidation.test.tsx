import { QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { queryClient } from '@/App';
import {
  useAllManagementKeys,
  useCreateInferenceKeyMutation,
  useInferenceKeys,
  useInstanceKeys,
  useMintInstanceKeyMutation,
  useRevokeInferenceKeyMutation,
  useRevokeInstanceKeyMutation,
  useRevokeManagementKeyMutation,
} from '@/features/keys/hooks';
import { ORG, server } from './msw';

const now = '2026-01-01T00:00:00Z';

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

function managementKey(status: string) {
  return {
    id: 'mk-1',
    org_id: ORG.id,
    name: 'ci-bot',
    status,
    created_at: now,
    updated_at: now,
    revoked_at: status === 'revoked' ? now : null,
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

function instanceKey(id: string, status: string) {
  return {
    id,
    label: 'ci',
    status,
    created_at: now,
    updated_at: now,
    revoked_at: status === 'revoked' ? now : null,
  };
}

describe('key cache invalidation across pages', () => {
  it('revoking a management key via the org-scoped mutation refetches the instance-wide list', async () => {
    // The instance-wide list serves ACTIVE until the revoke lands on the server.
    let revoked = false;
    let instanceListFetches = 0;
    server.use(
      http.get('/v1/instance/management-keys', () => {
        instanceListFetches += 1;
        return HttpResponse.json([managementKey(revoked ? 'revoked' : 'active')]);
      }),
      http.delete('/v1/org/management-keys/:keyId', () => {
        revoked = true;
        return HttpResponse.json({ id: 'mk-1', status: 'revoked' });
      }),
    );

    // A view backed by the instance-wide management-key list (user detail / dashboard).
    const list = renderHook(() => useAllManagementKeys(), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    expect(list.result.current.data).toEqual([expect.objectContaining({ status: 'active' })]);
    expect(instanceListFetches).toBe(1);

    // The org page revokes the key through its org-scoped mutation.
    const revoke = renderHook(() => useRevokeManagementKeyMutation(ORG.id), { wrapper });
    await revoke.result.current.mutateAsync({ keyId: 'mk-1' });

    // The instance-wide query must be invalidated and refetched with fresh status.
    await waitFor(() => expect(instanceListFetches).toBe(2));
    await waitFor(() =>
      expect(list.result.current.data).toEqual([expect.objectContaining({ status: 'revoked' })]),
    );
  });

  it('minting an instance key refetches the instance key list', async () => {
    const keys = [instanceKey('ik-1', 'active')];
    let listFetches = 0;
    server.use(
      http.get('/v1/instance/instance-keys', () => {
        listFetches += 1;
        return HttpResponse.json(keys);
      }),
      http.post('/v1/instance/instance-keys', () => {
        keys.push(instanceKey('ik-2', 'active'));
        return HttpResponse.json({ ...instanceKey('ik-2', 'active'), token: 'tok-once' });
      }),
    );

    const list = renderHook(() => useInstanceKeys(), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    expect(list.result.current.data).toHaveLength(1);
    expect(listFetches).toBe(1);

    const mint = renderHook(() => useMintInstanceKeyMutation(), { wrapper });
    await mint.result.current.mutateAsync({ data: { label: 'ci' } });

    await waitFor(() => expect(listFetches).toBe(2));
    await waitFor(() => expect(list.result.current.data).toHaveLength(2));
  });

  it('revoking an instance key refetches the instance key list with fresh status', async () => {
    let revoked = false;
    let listFetches = 0;
    server.use(
      http.get('/v1/instance/instance-keys', () => {
        listFetches += 1;
        return HttpResponse.json([instanceKey('ik-1', revoked ? 'revoked' : 'active')]);
      }),
      http.delete('/v1/instance/instance-keys/:keyId', () => {
        revoked = true;
        return HttpResponse.json({ id: 'ik-1', status: 'revoked' });
      }),
    );

    const list = renderHook(() => useInstanceKeys(), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    expect(list.result.current.data).toEqual([expect.objectContaining({ status: 'active' })]);

    const revoke = renderHook(() => useRevokeInstanceKeyMutation(), { wrapper });
    await revoke.result.current.mutateAsync({ keyId: 'ik-1' });

    await waitFor(() => expect(listFetches).toBe(2));
    await waitFor(() =>
      expect(list.result.current.data).toEqual([expect.objectContaining({ status: 'revoked' })]),
    );
  });

  it('minting an inference key refetches the workspace inference key list', async () => {
    const keys = [inferenceKey('ifk-1', false)];
    let listFetches = 0;
    server.use(
      http.get(`/v1/org/workspaces/${WORKSPACE_REF}/inference-keys`, () => {
        listFetches += 1;
        return HttpResponse.json(keys);
      }),
      http.post(`/v1/org/workspaces/${WORKSPACE_REF}/inference-keys`, () => {
        keys.push(inferenceKey('ifk-2', false));
        return HttpResponse.json({ id: 'ifk-2', token: 'tok-once' });
      }),
    );

    const list = renderHook(() => useInferenceKeys(ORG.id, WORKSPACE_REF), { wrapper });
    await waitFor(() => expect(list.result.current.isSuccess).toBe(true));
    expect(list.result.current.data).toHaveLength(1);
    expect(listFetches).toBe(1);

    const mint = renderHook(() => useCreateInferenceKeyMutation(ORG.id, WORKSPACE_REF), { wrapper });
    await mint.result.current.mutateAsync({ workspaceRef: WORKSPACE_REF, data: { label: 'app' } });

    await waitFor(() => expect(listFetches).toBe(2));
    await waitFor(() => expect(list.result.current.data).toHaveLength(2));
  });

  it('revoking an inference key refetches the workspace inference key list with fresh status', async () => {
    let revoked = false;
    let listFetches = 0;
    server.use(
      http.get(`/v1/org/workspaces/${WORKSPACE_REF}/inference-keys`, () => {
        listFetches += 1;
        return HttpResponse.json([inferenceKey('ifk-1', revoked)]);
      }),
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

    await waitFor(() => expect(listFetches).toBe(2));
    await waitFor(() =>
      expect(list.result.current.data).toEqual([expect.objectContaining({ revoked: true })]),
    );
  });
});
