import { Link, useLocation } from 'wouter';
import { Users, LogOut } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Avatar, AvatarFallback, Button } from '@/components/ui/elements';
import { useSession } from '@/lib/session';
import { GatewayBrand, ResponsiveShell } from '@/components/layout/responsive-shell';
import { useAuthorization } from '@/features/permissions/hooks';
import { instanceRoutes } from '@/pages/instance-routes';

export function Shell({ children }: { children: React.ReactNode }) {
  const [location] = useLocation();
  const { user, logout } = useSession();
  const authorization = useAuthorization('instance');
  const navigation = instanceRoutes.flatMap((route) =>
    route.navigation && authorization.can(route.access) ? [{ path: route.path, ...route.navigation }] : [],
  );
  const roleLabel = user?.instance_role === 'owner' ? 'Owner' : user?.instance_role === 'auditor' ? 'Auditor' : 'Data plane';

  const sidebar = (close: () => void) => (
    <div className="flex min-h-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="hidden h-16 shrink-0 items-center border-b border-sidebar-border/50 px-6 md:flex">
        <GatewayBrand href="/instance" />
      </div>
      <nav aria-label="Instance navigation" className="flex-1 space-y-1 px-4 py-6">
        <div className="mb-4 px-2 font-mono text-[10px] font-bold uppercase tracking-widest text-sidebar-foreground/50">Administration</div>
        {navigation.map((item) => {
          const isActive = location === item.path || (item.path !== '/instance' && location.startsWith(item.path));
          return (
            <Link
              key={item.path}
              href={item.path}
              onClick={close}
              aria-current={isActive ? 'page' : undefined}
              className={cn(
                'flex items-center gap-3 rounded-md border-l-2 px-3 py-2 font-mono text-[11px] font-bold uppercase tracking-wider transition-colors',
                isActive
                  ? 'border-primary bg-sidebar-accent text-sidebar-accent-foreground'
                  : 'border-transparent text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground',
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="shrink-0 border-t border-sidebar-border/50 p-4">
        <div className="mb-4 flex items-center gap-3 px-2">
          <Avatar aria-hidden="true" className="h-8 w-8">
            <AvatarFallback className="bg-sidebar-accent text-xs font-bold text-sidebar-accent-foreground">
              {user?.name?.charAt(0) || '?'}
            </AvatarFallback>
          </Avatar>
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-sm font-medium text-foreground">{user?.name}</span>
            <span className="text-xs text-sidebar-foreground/50">{roleLabel}</span>
          </div>
        </div>
        <Link
          href="/org"
          onClick={close}
          className="mb-2 flex items-center gap-3 rounded-md px-2 py-2 font-mono text-[11px] font-bold uppercase tracking-wider text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground"
        >
          <Users className="h-4 w-4" />
          Workspace console
        </Link>
        <Button
          variant="ghost"
          size="sm"
          onClick={logout}
          className="h-8 w-full justify-start px-2 text-sidebar-foreground/70 hover:text-destructive"
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </Button>
      </div>
    </div>
  );

  return (
    <ResponsiveShell
      brand={<GatewayBrand href="/instance" />}
      navigationLabel="Instance navigation"
      sidebar={sidebar}
      asideClassName="border-sidebar-border bg-sidebar shadow-xl"
      mainClassName="bg-background"
    >
      {children}
    </ResponsiveShell>
  );
}
