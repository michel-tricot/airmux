import { createContext, useContext, useState, ReactNode } from 'react';

interface SessionContextType {
  userId: number | null;
  orgId: number | null;
  setUserId: (id: number | null) => void;
  setOrgId: (id: number | null) => void;
  logout: () => void;
}

const SessionContext = createContext<SessionContextType | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [userId, setUserIdState] = useState<number | null>(() => {
    const saved = localStorage.getItem('gateway_userId');
    return saved ? Number(saved) : null;
  });
  const [orgId, setOrgIdState] = useState<number | null>(() => {
    const saved = localStorage.getItem('gateway_orgId');
    return saved ? Number(saved) : null;
  });

  const setUserId = (id: number | null) => {
    setUserIdState(id);
    if (id) localStorage.setItem('gateway_userId', id.toString());
    else localStorage.removeItem('gateway_userId');
  };

  const setOrgId = (id: number | null) => {
    setOrgIdState(id);
    if (id) localStorage.setItem('gateway_orgId', id.toString());
    else localStorage.removeItem('gateway_orgId');
  };

  const logout = () => {
    setUserId(null);
    setOrgId(null);
  };

  return (
    <SessionContext.Provider value={{ userId, orgId, setUserId, setOrgId, logout }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used within SessionProvider");
  return context;
}
