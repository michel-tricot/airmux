import { useEffect, useRef, useState } from 'react';
import * as z from 'zod';
import { useSession } from '@/lib/session';
import { useWorkspaces, useCreateWorkspaceMutation } from '@/features/workspaces/hooks';
import { Link, useLocation } from 'wouter';
import {
  TerminalSquare, Settings, LogOut, Shield, ArrowLeftRight,
  LayoutGrid, KeyRound, Database, Route as RouteIcon, ShieldCheck, Building2,
} from 'lucide-react';
import { Button, Input, Dropdown } from '@/components/ui/elements';
import { cn } from '@/lib/utils';
import { Plus } from 'lucide-react';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';

const workspaceNameSchema = z.object({ name: z.string().min(1, 'Name is required') });

const SECTIONS = [
  { label: 'Overview', suffix: '', icon: LayoutGrid },
  { label: 'API Keys', suffix: '/keys', icon: KeyRound },
  { label: 'BYOK', suffix: '/byok', icon: Database, soon: true },
  { label: 'Routing', suffix: '/routing', icon: RouteIcon, soon: true },
  { label: 'Policies', suffix: '/policies', icon: ShieldCheck, soon: true },
  { label: 'Settings', suffix: '/settings', icon: Settings },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, orgId, setOrgId, logout } = useSession();
  const { data: workspaces } = useWorkspaces(orgId!);
  const [location, setLocation] = useLocation();
  const [createOpen, setCreateOpen] = useState(false);

  // /org/workspaces/<slug>[/section] — the slug selects the workspace, the tail names the section.
  const match = location.match(/^\/org\/workspaces\/([^/]+)(\/[^/]+)?/);
  const activeWorkspaceRef = match?.[1] ?? '';
  const activeSuffix = match?.[2] ?? '';
  const activeWorkspace = workspaces?.find(ws => ws.slug === activeWorkspaceRef || ws.id === activeWorkspaceRef);
  const activeWorkspaceSlug = activeWorkspace?.slug ?? activeWorkspaceRef;

  const switchWorkspace = (slug: string) => {
    // Keep the section when hopping between workspaces so the context survives the switch.
    setLocation(`/org/workspaces/${slug}${activeSuffix}`);
  };

  // Remember the last-selected workspace per org so returning users land where they left off.
  const lastWsKey = `airllm_last_ws_${orgId}`;
  useEffect(() => {
    if (activeWorkspaceSlug) localStorage.setItem(lastWsKey, activeWorkspaceSlug);
  }, [activeWorkspaceSlug, lastWsKey]);

  // Normalize old UUID-based links to the canonical slug URL.
  useEffect(() => {
    if (activeWorkspace && activeWorkspaceRef !== activeWorkspace.slug) {
      setLocation(`/org/workspaces/${activeWorkspace.slug}${activeSuffix}`, { replace: true });
    }
  }, [activeWorkspace, activeWorkspaceRef, activeSuffix, setLocation]);

  // On first entry at /org, jump to the last-selected (or first) workspace by default.
  // Only once per layout mount, so the "Organization → Overview" nav link stays reachable.
  const autoPicked = useRef(false);
  useEffect(() => {
    if (autoPicked.current || !workspaces) return;
    autoPicked.current = true;
    if (location !== '/org' || workspaces.length === 0) return;
    const last = localStorage.getItem(lastWsKey);
    const target = workspaces.find(ws => ws.slug === last || ws.id === last) ?? workspaces[0];
    setLocation(`/org/workspaces/${target.slug}`, { replace: true });
  }, [workspaces, location, lastWsKey, setLocation]);

  const createWorkspace = useCreateWorkspaceMutation(orgId!);

  return (
    <div className="h-[100dvh] flex w-full overflow-hidden bg-background font-sans">
      {/* Sidebar */}
      <aside className="w-64 flex-col bg-card text-card-foreground flex border-r border-border shadow-sm shrink-0">
        <div className="h-14 flex items-center justify-between gap-2 px-4 border-b border-border/50 shrink-0">
          <Link href="/org" className="flex min-w-0 items-center gap-3 font-mono font-bold tracking-widest text-foreground hover:text-primary transition-colors">
            <div className="w-6 h-6 rounded bg-primary flex items-center justify-center shadow-[0_0_12px_rgba(97,94,255,0.4)] shrink-0">
              <TerminalSquare className="w-4 h-4 text-primary-foreground" />
            </div>
            <span><span aria-hidden="true" className="text-primary opacity-70 mr-1">$</span>GATEWAY</span>
          </Link>
          <Button
            variant="ghost"
            size="icon"
            title="Switch organization"
            aria-label="Switch organization"
            onClick={() => {
              setOrgId(null);
              setLocation('/orgs');
            }}
            className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
          >
            <ArrowLeftRight className="w-4 h-4" />
          </Button>
        </div>

        <div className="p-3 border-b border-border/50 shrink-0">
          <Dropdown
            value={activeWorkspaceSlug}
            onValueChange={switchWorkspace}
            aria-label="Workspace"
            placeholder="Select a workspace"
            className="bg-muted font-medium"
            options={(workspaces ?? []).map(ws => ({ value: ws.slug, label: ws.name }))}
            actions={[{ label: 'Create Workspace', icon: <Plus className="h-4 w-4" />, onSelect: () => setCreateOpen(true) }]}
          />
        </div>

        <nav className="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
          {activeWorkspaceSlug ? (
            SECTIONS.map(({ label, suffix, icon: Icon, soon }) => {
              const href = `/org/workspaces/${activeWorkspaceSlug}${suffix}`;
              const isActive = location === href;
              return (
                <Link key={suffix} href={href} className={cn(
                  "flex items-center gap-3 px-3 py-2 rounded-md text-[11px] font-mono font-bold uppercase tracking-wider transition-all duration-200",
                  isActive
                    ? "bg-primary/10 text-primary shadow-[inset_3px_0_0_0_rgba(97,94,255,1)]"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}>
                  <Icon className="w-4 h-4 shrink-0" />
                  <span className="truncate">{label}</span>
                  {soon && (
                    <span className="ml-auto inline-flex items-center rounded-full border border-primary/20 bg-primary/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-primary">
                      Soon
                    </span>
                  )}
                </Link>
              );
            })
          ) : (
            <div className="px-3 py-2 text-xs text-muted-foreground italic">
              {workspaces?.length === 0 ? 'No workspaces in this organization.' : 'Select a workspace above.'}
            </div>
          )}

          <div className="mt-8">
            <div className="text-[10px] font-mono font-bold text-muted-foreground/50 uppercase tracking-widest mb-2 px-3 mt-6">Organization</div>
            <Link href="/org" className={cn(
              "flex items-center gap-3 px-3 py-2 rounded-md text-[11px] font-mono font-bold uppercase tracking-wider transition-all duration-200",
              location === '/org'
                ? "bg-primary/10 text-primary shadow-[inset_3px_0_0_0_rgba(97,94,255,1)]"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            )}>
              <Building2 className="w-4 h-4 shrink-0" />
              Overview
            </Link>
            <Link href="/org/settings" className={cn(
              "flex items-center gap-3 px-3 py-2 rounded-md text-[11px] font-mono font-bold uppercase tracking-wider transition-all duration-200",
              location === '/org/settings'
                ? "bg-primary/10 text-primary shadow-[inset_3px_0_0_0_rgba(97,94,255,1)]"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            )}>
              <Settings className="w-4 h-4 shrink-0" />
              Org Settings
            </Link>
          </div>
        </nav>

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
            {user?.instance_admin && (
              <Link href="/instance">
                <Button variant="ghost" size="icon" title="Instance Admin" className="text-muted-foreground hover:text-primary h-8 w-8 shrink-0">
                  <Shield className="w-4 h-4" />
                </Button>
              </Link>
            )}
          </div>
        </div>
      </aside>

      <main className="flex-1 flex flex-col min-w-0 overflow-auto bg-muted/20 relative">
        {children}
      </main>

      <FormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New Workspace"
        description="Workspaces group inference keys and members within your organization."
        schema={workspaceNameSchema}
        defaultValues={{ name: '' }}
        onSubmit={async values => {
          const created = await createWorkspace.mutateAsync({ data: values });
          setLocation(`/org/workspaces/${created.slug}`);
        }}
        submitLabel="Create"
        pending={createWorkspace.isPending}>
        {form => (
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Name</FormLabel>
                <FormControl>
                  <Input autoFocus placeholder="e.g. production" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        )}
      </FormDialog>
    </div>
  );
}
