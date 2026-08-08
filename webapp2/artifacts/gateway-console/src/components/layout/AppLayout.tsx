import { useSession } from '@/lib/session';
import { useGetUser, useListUserOrganizations, useListUserWorkspaces, getGetUserQueryKey, getListUserOrganizationsQueryKey, getListUserWorkspacesQueryKey } from '@workspace/api-client-react';
import { Link, useLocation } from 'wouter';
import { TerminalSquare, Settings, LogOut, Shield, FolderGit2 } from 'lucide-react';
import { Button } from '@/components/ui/elements';
import { useEffect } from 'react';
import { cn } from '@/lib/utils';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { userId, orgId, setOrgId, logout } = useSession();
  const { data: user, isError: userError } = useGetUser(userId!, { query: { enabled: !!userId, queryKey: getGetUserQueryKey(userId!), retry: 0 }});
  const { data: orgs, isError: orgsError } = useListUserOrganizations(userId!, { query: { enabled: !!userId, queryKey: getListUserOrganizationsQueryKey(userId!), retry: 0 }});
  const { data: workspaces } = useListUserWorkspaces(userId!, { query: { enabled: !!userId && !!orgId, queryKey: getListUserWorkspacesQueryKey(userId!) }});
  const [location] = useLocation();

  useEffect(() => {
    if (userError || orgsError) {
      logout();
    } else if (orgs && orgId) {
      if (!orgs.some(o => o.orgId === orgId)) {
        setOrgId(null);
      }
    }
  }, [userError, orgsError, orgs, orgId, logout, setOrgId]);

  const activeOrg = orgs?.find(o => o.orgId === orgId);
  const isOwnerOrAdmin = activeOrg?.role === 'owner' || activeOrg?.role === 'admin';
  const orgWorkspaces = workspaces?.filter(w => w.orgId === orgId) || [];

  return (
    <div className="h-[100dvh] flex w-full overflow-hidden bg-background font-sans">
      {/* Sidebar */}
      <aside className="w-64 flex-col bg-card text-card-foreground flex border-r border-border shadow-sm shrink-0">
        <div className="h-14 flex items-center px-6 border-b border-border/50 shrink-0">
          <Link href="/app" className="flex items-center gap-2 font-mono font-bold tracking-tight text-foreground hover:text-primary transition-colors">
            <div className="w-6 h-6 rounded bg-primary flex items-center justify-center shadow-[0_0_8px_rgba(255,255,255,0.1)]">
              <TerminalSquare className="w-4 h-4 text-primary-foreground" />
            </div>
            GATEWAY
          </Link>
        </div>

        <div className="p-4 border-b border-border/50 shrink-0">
          <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2 px-1">Organization</div>
          <select 
            value={orgId || ''} 
            onChange={e => setOrgId(Number(e.target.value))}
            className="w-full bg-muted border border-input hover:border-border rounded-md text-sm font-medium focus:ring-1 focus:ring-primary focus:outline-none px-3 py-2 cursor-pointer transition-colors"
          >
            {orgs?.map(o => (
              <option key={o.orgId} value={o.orgId}>{o.orgName}</option>
            ))}
          </select>
        </div>

        <div className="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
          <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2 px-3 mt-2">
            Workspaces
          </div>
          
          {orgWorkspaces.map((ws) => {
            const isActive = location === `/app/workspaces/${ws.id}`;
            return (
              <Link key={ws.id} href={`/app/workspaces/${ws.id}`} className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-all duration-200",
                isActive 
                  ? "bg-primary/10 text-primary" 
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}>
                <FolderGit2 className="w-4 h-4 shrink-0" />
                <span className="truncate">{ws.name}</span>
              </Link>
            );
          })}
          
          {orgWorkspaces.length === 0 && (
            <div className="px-3 py-2 text-xs text-muted-foreground italic">No workspaces found.</div>
          )}

          {isOwnerOrAdmin && (
            <div className="mt-8">
              <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2 px-3 mt-6">Settings</div>
              <Link href="/app/settings" className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-all duration-200",
                location === '/app/settings'
                  ? "bg-primary/10 text-primary" 
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}>
                <Settings className="w-4 h-4 shrink-0" />
                Org Settings
              </Link>
            </div>
          )}
        </div>

        <div className="p-4 border-t border-border/50 shrink-0 bg-muted/30">
          <div className="flex items-center gap-3 px-1 mb-4">
            <div className="w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center font-bold text-sm shadow-sm shrink-0">
              {user?.name?.charAt(0) || '?'}
            </div>
            <div className="flex flex-col min-w-0 flex-1">
              <span className="text-sm font-medium text-foreground truncate leading-tight">{user?.name}</span>
              <span className="text-xs text-muted-foreground truncate">{user?.email}</span>
            </div>
          </div>
          <div className="flex items-center gap-1 justify-between px-1">
            <Button variant="ghost" size="sm" onClick={logout} className="text-muted-foreground hover:text-destructive h-8 px-2 justify-start flex-1">
              <LogOut className="w-4 h-4 mr-2 shrink-0" />
              Sign out
            </Button>
            <Link href="/">
              <Button variant="ghost" size="icon" title="Instance Admin" className="text-muted-foreground hover:text-primary h-8 w-8 shrink-0">
                <Shield className="w-4 h-4" />
              </Button>
            </Link>
          </div>
        </div>
      </aside>
      
      <main className="flex-1 flex flex-col min-w-0 overflow-auto bg-muted/20 relative">
        {children}
      </main>
    </div>
  );
}
