import { createContext, useCallback, useContext, useState, ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useMe, useLogout, getMeQueryKey, type MeOut } from '@workspace/api-client-react';
import { ORG_SCOPE_ROOT } from '@/lib/query-keys';

const ORG_STORAGE_KEY = 'airllm_org_id';

interface SessionContextType {
  user: MeOut | undefined;
  isLoading: boolean;
  orgId: string | null;
  setOrgId: (id: string | null) => void;
  logout: () => void;
}

const SessionContext = createContext<SessionContextType | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { data: user, isLoading } = useMe({ query: { queryKey: getMeQueryKey(), retry: false } });
  const [orgId, setOrgIdState] = useState<string | null>(() => localStorage.getItem(ORG_STORAGE_KEY));

  // Org-scoped queries all live under ORG_SCOPE_ROOT (see lib/query-keys.ts), so leaving an
  // org drops that whole subtree in one key-based call rather than a predicate scan.
  const setOrgId = useCallback((id: string | null) => {
    setOrgIdState(id);
    if (id) localStorage.setItem(ORG_STORAGE_KEY, id);
    else localStorage.removeItem(ORG_STORAGE_KEY);
    queryClient.removeQueries({ queryKey: ORG_SCOPE_ROOT });
  }, [queryClient]);

  const logoutMutation = useLogout();
  const logout = useCallback(() => {
    logoutMutation.mutate(undefined, {
      onSettled: () => {
        // The stored org is kept so the next sign-in lands back in it; if another
        // account signs in here, the enrollment check bounces them to the picker.
        queryClient.clear();
      },
    });
  }, [logoutMutation, queryClient]);

  return (
    <SessionContext.Provider value={{ user, isLoading, orgId, setOrgId, logout }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) throw new Error('useSession must be used within SessionProvider');
  return context;
}
