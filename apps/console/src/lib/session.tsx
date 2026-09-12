import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useMe, useLogout, getMeQueryKey, type MeOut } from '@workspace/api-client-react';

const ORG_STORAGE_KEY = 'airllm_org_id';

interface SessionContextType {
  user: MeOut | undefined;
  isLoading: boolean;
  error: unknown;
  orgId: string | null;
  setOrgId: (id: string | null) => void;
  logout: () => void;
  retry: () => void;
  isRetrying: boolean;
}

const SessionContext = createContext<SessionContextType | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const session = useMe({ query: { queryKey: getMeQueryKey(), retry: false } });
  const [orgId, setOrgIdState] = useState<string | null>(() => window.localStorage.getItem(ORG_STORAGE_KEY));

  const setOrgId = useCallback(
    (id: string | null) => {
      if (orgId && orgId !== id) {
        void queryClient.cancelQueries();
        queryClient.clear();
      }
      setOrgIdState(id);
      if (id) window.localStorage.setItem(ORG_STORAGE_KEY, id);
      else window.localStorage.removeItem(ORG_STORAGE_KEY);
    },
    [orgId, queryClient],
  );

  const logoutMutation = useLogout();
  const logout = useCallback(() => {
    logoutMutation.mutate(undefined, {
      onSettled: () => {
        setOrgId(null);
        queryClient.clear();
      },
    });
  }, [logoutMutation, queryClient, setOrgId]);

  const user = session.isError ? undefined : session.data;
  const { refetch } = session;
  const retry = useCallback(() => {
    void refetch();
  }, [refetch]);

  return (
    <SessionContext.Provider
      value={{ user, isLoading: session.isLoading, error: session.error, orgId, setOrgId, logout, retry, isRetrying: session.isRefetching }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) throw new Error('useSession must be used within SessionProvider');
  return context;
}

export function useRequiredOrgId(): string {
  const { orgId } = useSession();
  if (!orgId) throw new Error('Organization scope is required');
  return orgId;
}
