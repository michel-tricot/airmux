import { useQueryClient } from '@tanstack/react-query';
import {
  useListWorkspaces,
  useGetWorkspace,
  useCreateWorkspace,
  useUpdateWorkspace,
  useDeleteWorkspace,
  getListWorkspacesQueryKey,
  getGetWorkspaceQueryKey,
} from '@workspace/api-client-react';
import { orgScope } from '@/lib/api';
import { orgScopedKey } from '@/lib/query-keys';

/** All workspaces in the given org. */
export function useWorkspaces(orgId: string) {
  return useListWorkspaces({
    query: { queryKey: orgScopedKey(orgId, getListWorkspacesQueryKey()) },
    request: orgScope(orgId),
  });
}

/** One workspace by slug or id within the given org. */
export function useWorkspace(orgId: string, workspaceRef: string) {
  return useGetWorkspace(workspaceRef, {
    query: { queryKey: orgScopedKey(orgId, getGetWorkspaceQueryKey(workspaceRef)), retry: false },
    request: orgScope(orgId),
  });
}

export function useCreateWorkspaceMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useCreateWorkspace({
    mutation: {
      onSuccess: () =>
        queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, getListWorkspacesQueryKey()) }),
      meta: { errorMessage: 'We couldn’t create the workspace. Please try again.' },
    },
    request: orgScope(orgId),
  });
}

export function useRenameWorkspaceMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useUpdateWorkspace({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, getListWorkspacesQueryKey()) });
        queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, getGetWorkspaceQueryKey(workspaceRef)) });
      },
      meta: { errorMessage: 'We couldn’t rename the workspace. Please try again.' },
    },
    request: orgScope(orgId),
  });
}

export function useDeleteWorkspaceMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useDeleteWorkspace({
    mutation: {
      onSuccess: () =>
        queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, getListWorkspacesQueryKey()) }),
      meta: { errorMessage: 'We couldn’t delete this workspace. Please try again.' },
    },
    request: orgScope(orgId),
  });
}
