import type { ReactNode } from 'react';
import { LogOut, type LucideIcon } from 'lucide-react';
import { Link } from 'wouter';
import { AirmuxBrand } from '@/components/layout/responsive-shell';
import { Avatar, AvatarFallback, Button } from '@/components/ui/elements';
import { useSession } from '@/lib/session';
import { cn } from '@/lib/utils';

export function ConsoleSidebar({
  homeHref,
  onNavigate,
  headerAction,
  accountDescription,
  switchConsole,
  children,
}: {
  homeHref: string;
  onNavigate: () => void;
  headerAction?: ReactNode;
  accountDescription?: string;
  switchConsole?: { href: string; label: string; icon: LucideIcon };
  children: ReactNode;
}) {
  const { user, logout } = useSession();

  return (
    <div className="flex min-h-full flex-col bg-card text-card-foreground">
      <div className="hidden h-14 shrink-0 items-center justify-between gap-2 border-b border-border/50 px-4 md:flex">
        <AirmuxBrand href={homeHref} onClick={onNavigate} />
        {headerAction}
      </div>
      {children}
      <div className="shrink-0 border-t border-border/50 bg-muted/30 p-4">
        <div className="mb-4 flex items-center gap-3 px-1">
          <Avatar aria-hidden="true" className="h-8 w-8">
            <AvatarFallback className="bg-primary/10 text-sm font-bold text-primary">{user?.name?.charAt(0) || '?'}</AvatarFallback>
          </Avatar>
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-sm font-medium leading-tight text-foreground">{user?.name}</span>
            <span className="truncate text-xs text-muted-foreground">{accountDescription ?? user?.email}</span>
          </div>
        </div>
        <div className="flex items-center justify-between gap-1 px-1">
          <Button variant="ghost" size="sm" onClick={logout} className="h-8 flex-1 justify-start px-2 text-muted-foreground hover:text-destructive">
            <LogOut className="h-4 w-4 shrink-0" />
            Sign out
          </Button>
          {switchConsole && (
            <Button asChild variant="ghost" size="icon" className="h-8 w-8 shrink-0 text-muted-foreground hover:text-primary">
              <Link href={switchConsole.href} onClick={onNavigate} title={switchConsole.label} aria-label={switchConsole.label}>
                <switchConsole.icon className="h-4 w-4" />
              </Link>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export function ConsoleNavigationLink({
  href,
  label,
  icon: Icon,
  active,
  onNavigate,
}: {
  href: string;
  label: string;
  icon: LucideIcon;
  active: boolean;
  onNavigate: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex items-center gap-3 rounded-md border-l-2 px-3 py-2 font-mono text-[11px] font-bold uppercase tracking-wider transition-colors',
        active ? 'border-primary bg-primary/10 text-primary' : 'border-transparent text-muted-foreground hover:bg-muted hover:text-foreground',
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="truncate">{label}</span>
    </Link>
  );
}

export function ConsoleNavigationHeading({ children }: { children: ReactNode }) {
  return <div className="mb-2 px-3 font-mono text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50">{children}</div>;
}
