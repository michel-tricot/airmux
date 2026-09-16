import { useQueryClient } from '@tanstack/react-query';
import {
  useListWorkspacesInfinite,
  useGetWorkspace,
  useCreateWorkspace,
  useUpdateWorkspace,
  useDeleteWorkspace,
  getListWorkspacesInfiniteQueryKey,
  getGetWorkspaceQueryKey,
} from '@workspace/api-client-react';
import type { EnabledQueryOptions } from '@/features/query-options';
import { flattenPages, paginatedQueryOptions } from '@/features/pagination';

export function useWorkspaces(orgId: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useListWorkspacesInfinite(orgId, undefined, { query: { enabled, ...paginatedQueryOptions, select: flattenPages } });
}

export function useWorkspace(orgId: string, workspaceRef: string, { enabled = true }: EnabledQueryOptions = {}) {
  return useGetWorkspace(orgId, workspaceRef, { query: { enabled, retry: false } });
}

export function useCreateWorkspaceMutation(orgId: string) {
  const queryClient = useQueryClient();
  return useCreateWorkspace({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListWorkspacesInfiniteQueryKey(orgId) }),
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
          queryClient.invalidateQueries({ queryKey: getListWorkspacesInfiniteQueryKey(orgId) }),
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
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getListWorkspacesInfiniteQueryKey(orgId) }),
      meta: { errorMessage: 'We couldn’t delete this workspace. Please try again.' },
    },
  });
}
