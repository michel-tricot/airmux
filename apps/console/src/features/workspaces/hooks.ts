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
import type { EnabledQueryOptions } from '@/features/query-options';

export function useWorkspaces(orgId: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListWorkspaces(orgId, { query: { enabled } });
}

export function useWorkspace(orgId: string, workspaceRef: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useGetWorkspace(orgId, workspaceRef, { query: { enabled, retry: false } });
}

export function useCreateWorkspaceMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useCreateWorkspace({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListWorkspacesQueryKey(orgId) }),
      meta: { errorMessage: 'We couldn’t create the workspace. Please try again.' },
    },
  });
}

export function useRenameWorkspaceMutation(orgId: string, workspaceRef: string) {
  const queryClient = useQueryClient();
  return useUpdateWorkspace({
    mutation: {
      onSuccess: () =>
        Promise.all([
          queryClient.invalidateQueries({ queryKey: getListWorkspacesQueryKey(orgId) }),
          queryClient.invalidateQueries({ queryKey: getGetWorkspaceQueryKey(orgId, workspaceRef) }),
        ]),
      meta: { errorMessage: 'We couldn’t rename the workspace. Please try again.' },
    },
  });
}

export function useDeleteWorkspaceMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useDeleteWorkspace({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListWorkspacesQueryKey(orgId) }),
      meta: { errorMessage: 'We couldn’t delete this workspace. Please try again.' },
    },
  });
}
