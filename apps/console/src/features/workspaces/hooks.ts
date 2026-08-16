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

export function useWorkspaces(orgId: string) {
  return useListWorkspaces(orgId);
}

export function useWorkspace(orgId: string, workspaceRef: string) {
  return useGetWorkspace(orgId, workspaceRef, { query: { queryKey: getGetWorkspaceQueryKey(orgId, workspaceRef), retry: false } });
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
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListWorkspacesQueryKey(orgId) });
        queryClient.invalidateQueries({ queryKey: getGetWorkspaceQueryKey(orgId, workspaceRef) });
      },
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
