import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useMe, useLogout, getMeQueryKey, type MeOut } from '@workspace/api-client-react';
import { ORG_SCOPE_ROOT } from '@/lib/query-keys';

const ORG_STORAGE_KEY = 'airllm_org_id';

interface SessionContextType {
  user: MeOut | undefined;
  isLoading: boolean;
  error: unknown;
  orgId: string | null;
  setOrgId: (id: string | null) => void;
  logout: () => void;
}

const SessionContext = createContext<SessionContextType | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const session = useMe({ query: { queryKey: getMeQueryKey(), retry: false } });
  const [orgId, setOrgIdState] = useState<string | null>(() => window.localStorage.getItem(ORG_STORAGE_KEY));

  const setOrgId = useCallback(
    (id: string | null) => {
      setOrgIdState(id);
      if (id) window.localStorage.setItem(ORG_STORAGE_KEY, id);
      else window.localStorage.removeItem(ORG_STORAGE_KEY);
      queryClient.removeQueries({ queryKey: ORG_SCOPE_ROOT });
    },
    [queryClient],
  );

  const logoutMutation = useLogout();
  const logout = useCallback(() => {
    logoutMutation.mutate(undefined, {
      onSettled: () => {
        queryClient.clear();
      },
    });
  }, [logoutMutation, queryClient]);

  const user = session.isError ? undefined : session.data;

  return (
    <SessionContext.Provider value={{ user, isLoading: session.isLoading, error: session.error, orgId, setOrgId, logout }}>
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
