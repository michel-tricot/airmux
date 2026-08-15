import { useState, type ReactNode } from 'react';
import { Menu, TerminalSquare } from 'lucide-react';
import { Link } from 'wouter';
import { Button, Modal } from '@/components/ui/elements';
import { cn } from '@/lib/utils';

interface ResponsiveShellProps {
  brand: ReactNode;
  navigationLabel: string;
  sidebar: (close: () => void) => ReactNode;
  children: ReactNode;
  asideClassName?: string;
  mainClassName?: string;
}

export function GatewayBrand({ href, onClick }: { href: string; onClick?: () => void }) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className="flex items-center gap-3 font-mono font-bold tracking-widest text-foreground transition-colors hover:text-primary"
    >
      <span className="flex h-6 w-6 items-center justify-center rounded bg-primary">
        <TerminalSquare className="h-4 w-4 text-primary-foreground" />
      </span>
      <span>GATEWAY</span>
    </Link>
  );
}

export function ResponsiveShell({ brand, navigationLabel, sidebar, children, asideClassName, mainClassName }: ResponsiveShellProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex h-[100dvh] w-full overflow-hidden bg-background font-sans">
      <aside className={cn('hidden w-64 shrink-0 flex-col border-r md:flex', asideClassName)}>{sidebar(() => undefined)}</aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-card px-4 md:hidden">
          {brand}
          <Button variant="ghost" size="icon" aria-label={`Open ${navigationLabel}`} onClick={() => setOpen(true)}>
            <Menu className="h-5 w-5" />
          </Button>
        </header>
        <main className={cn('relative flex min-w-0 flex-1 flex-col overflow-auto', mainClassName)}>{children}</main>
      </div>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title={navigationLabel}
        contentClassName="left-0 top-0 h-[100dvh] w-[min(20rem,calc(100%-2rem))] max-w-none translate-x-0 translate-y-0 grid-rows-[auto_1fr] gap-0 overflow-hidden rounded-none p-0"
      >
        <div className="min-h-0 overflow-y-auto">{sidebar(() => setOpen(false))}</div>
      </Modal>
    </div>
  );
}
