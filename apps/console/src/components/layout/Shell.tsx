import { Link, useLocation } from 'wouter';
import { LayoutDashboard, Building2, Users, TerminalSquare, LogOut } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/elements';
import { useSession } from '@/lib/session';

export function Shell({ children }: { children: React.ReactNode }) {
  const [location] = useLocation();
  const { user, logout } = useSession();

  const navItems = [
    { href: '/instance', label: 'Overview', icon: LayoutDashboard },
    { href: '/instance/organizations', label: 'Organizations', icon: Building2 },
    { href: '/instance/users', label: 'Users', icon: Users },
  ];

  return (
    <div className="flex h-[100dvh] w-full overflow-hidden bg-background font-sans">
      <aside className="w-64 flex-col bg-sidebar text-sidebar-foreground flex border-r border-sidebar-border shadow-2xl">
        <div className="h-16 flex items-center px-6 border-b border-sidebar-border/50">
          <div className="flex items-center gap-2 font-mono font-bold tracking-tight text-foreground text-lg">
            <div className="w-6 h-6 rounded bg-primary flex items-center justify-center shadow-[0_0_10px_rgba(255,255,255,0.1)]">
              <TerminalSquare className="w-4 h-4 text-primary-foreground" />
            </div>
            GATEWAY
          </div>
        </div>
        <div className="flex-1 py-6 px-4 space-y-1">
          <div className="text-xs font-semibold text-sidebar-foreground/50 uppercase tracking-wider mb-4 px-2">Control Plane</div>
          {navItems.map((item) => {
            const isActive = location === item.href || (item.href !== '/instance' && location.startsWith(item.href));
            return (
              <Link key={item.href} href={item.href} className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-all duration-200",
                isActive
                  ? "bg-sidebar-primary text-sidebar-primary-foreground shadow-sm"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              )}>
                <item.icon className="w-4 h-4" />
                {item.label}
              </Link>
            );
          })}
        </div>
        <div className="p-4 border-t border-sidebar-border/50">
          <div className="flex items-center gap-3 px-2 mb-4">
            <div className="w-8 h-8 rounded-full bg-sidebar-accent flex items-center justify-center text-xs font-bold text-sidebar-accent-foreground shadow-inner">
              {user?.name?.charAt(0) || '?'}
            </div>
            <div className="flex flex-col min-w-0">
              <span className="text-sm font-medium text-foreground truncate">{user?.name}</span>
              <span className="text-xs text-sidebar-foreground/50">Instance admin</span>
            </div>
          </div>
          <Link href="/org" className="flex flex-1 items-center gap-2 px-2 py-2 mb-2 rounded-md text-sm font-medium text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground transition-all duration-200">
            <Users className="w-4 h-4" />
            User console
          </Link>
          <Button variant="ghost" size="sm" onClick={logout} className="w-full justify-start text-sidebar-foreground/70 hover:text-destructive h-8 px-2">
            <LogOut className="w-4 h-4 mr-2" />
            Sign out
          </Button>
        </div>
      </aside>
      <main className="flex-1 flex flex-col min-w-0 overflow-auto bg-background">
        {children}
      </main>
    </div>
  );
}
