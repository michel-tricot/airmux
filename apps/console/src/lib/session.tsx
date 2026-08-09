import { createContext, useCallback, useContext, useState, ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useMe, useLogout, getMeQueryKey, type MeOut } from '@workspace/api-client-react';

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

  // The org travels in the X-Org-Id header, and the generated query keys are paths alone, so
  // everything already cached from /v1/org belongs to the org being left.
  const setOrgId = useCallback((id: string | null) => {
    setOrgIdState(id);
    if (id) localStorage.setItem(ORG_STORAGE_KEY, id);
    else localStorage.removeItem(ORG_STORAGE_KEY);
    queryClient.removeQueries({ predicate: query => String(query.queryKey[0]).startsWith('/v1/org') });
  }, [queryClient]);

  const logoutMutation = useLogout();
  const logout = useCallback(() => {
    logoutMutation.mutate(undefined, {
      onSettled: () => {
        localStorage.removeItem(ORG_STORAGE_KEY);
        setOrgIdState(null);
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
