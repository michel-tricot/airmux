import { useEffect, useState } from 'react';
import * as z from 'zod';
import { useRequiredOrgId, useSession } from '@/lib/session';
import { useWorkspaces, useCreateWorkspaceMutation } from '@/features/workspaces/hooks';
import { Link, useLocation, useSearch } from 'wouter';
import { LogOut, Shield, ArrowLeftRight, Plus } from 'lucide-react';
import { useEnrollment } from '@workspace/api-client-react';
import { Avatar, AvatarFallback, Button, Input, Dropdown } from '@/components/ui/elements';
import { cn } from '@/lib/utils';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { ErrorState } from '@/components/shared/states';
import { GatewayBrand, ResponsiveShell } from '@/components/layout/responsive-shell';
import { useAuthorization, useScopedAuthorization } from '@/features/permissions/hooks';
import { workspaceAccess } from '@/features/workspaces/policy';
import { workspaceRoutes } from '@/pages/app/workspace/routes';
import { orgRoutes } from '@/pages/app/routes';

const workspaceNameSchema = z.object({ name: z.string().min(1, 'Name is required') });
const ALL_WORKSPACES = '__all_workspaces__';

const navigationClassName =
  'flex items-center gap-3 rounded-md border-l-2 px-3 py-2 font-mono text-[11px] font-bold uppercase tracking-wider transition-colors';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, setOrgId, logout } = useSession();
  const orgId = useRequiredOrgId();
  const orgAuthorization = useAuthorization('org');
  const canListWorkspaces = orgAuthorization.can(workspaceAccess.list);
  const workspacesQuery = useWorkspaces(orgId, { enabled: canListWorkspaces });
  const workspaces = workspacesQuery.data;
  const enrollment = useEnrollment();
  const canSwitchOrg = (enrollment.data?.orgs.length ?? 0) > 1;
  const [location, setLocation] = useLocation();
  const search = useSearch();
  const [createOpen, setCreateOpen] = useState(false);

  const match = location.match(/^\/org\/workspaces\/([^/]+)(\/[^/]+)?/);
  const routedWorkspaceRef = match?.[1] ?? '';
  const activeSuffix = match?.[2] ?? '';
  const lastWorkspaceKey = `airmux_last_ws_${orgId}`;
  const activeWorkspace = workspaces?.find((workspace) => workspace.slug === routedWorkspaceRef);
  const activeWorkspaceSlug = activeWorkspace?.slug ?? routedWorkspaceRef;
  const workspaceAuthorization = useScopedAuthorization(
    { level: 'workspace', orgId, workspaceRef: activeWorkspaceSlug },
    { enabled: activeWorkspaceSlug !== '' },
  );
  const canCreateWorkspace = orgAuthorization.can(workspaceAccess.create);

  useEffect(() => {
    if (activeWorkspaceSlug) window.localStorage.setItem(lastWorkspaceKey, activeWorkspaceSlug);
  }, [activeWorkspaceSlug, lastWorkspaceKey]);

  const createWorkspace = useCreateWorkspaceMutation(orgId);
  const switchWorkspace = (slug: string) => {
    const overviewRoute = location === '/org' || (activeSuffix === '' && routedWorkspaceRef !== '');
    const requestsRoute = location === '/org/requests' || activeSuffix === '/requests';
    const preserveFilters = overviewRoute || requestsRoute;
    const nextSearch = new URLSearchParams(preserveFilters ? search : '');
    nextSearch.delete('request');
    nextSearch.delete('as_of');
    if (slug !== ALL_WORKSPACES) nextSearch.delete('workspace');
    const query = nextSearch.size ? `?${nextSearch}` : '';
    const suffix = requestsRoute ? '/requests' : activeSuffix;
    setLocation(slug === ALL_WORKSPACES ? `/org${requestsRoute ? '/requests' : ''}${query}` : `/org/workspaces/${slug}${suffix}${query}`);
  };

  const sidebar = (close: () => void) => (
    <div className="flex min-h-full flex-col bg-card text-card-foreground">
      <div className="hidden h-14 shrink-0 items-center justify-between gap-2 border-b border-border/50 px-4 md:flex">
        <GatewayBrand href="/org" onClick={close} />
        {canSwitchOrg && (
          <Button
            variant="ghost"
            size="icon"
            title="Switch organization"
            aria-label="Switch organization"
            onClick={() => {
              close();
              setOrgId(null);
              setLocation('/orgs');
            }}
            className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
          >
            <ArrowLeftRight className="h-4 w-4" />
          </Button>
        )}
      </div>

      <div className="shrink-0 border-b border-border/50 p-3">
        <Dropdown
          value={activeWorkspaceSlug || ALL_WORKSPACES}
          onValueChange={(slug) => {
            close();
            switchWorkspace(slug);
          }}
          aria-label="Workspace"
          placeholder={workspacesQuery.isLoading ? 'Loading workspaces...' : 'Select a workspace'}
          disabled={workspacesQuery.isLoading || workspacesQuery.isError}
          className="bg-muted font-medium"
          options={[
            { value: ALL_WORKSPACES, label: 'All workspaces' },
            ...(workspaces ?? []).map((workspace) => ({ value: workspace.slug, label: workspace.name })),
          ]}
          actions={
            canCreateWorkspace
              ? [
                  {
                    label: 'Create Workspace',
                    icon: <Plus className="h-4 w-4" />,
                    onSelect: () => {
                      close();
                      setCreateOpen(true);
                    },
                  },
                ]
              : []
          }
        />
      </div>

      {workspacesQuery.isError ? (
        <ErrorState error={workspacesQuery.error} resource="workspaces" onRetry={() => workspacesQuery.refetch()} className="p-4" />
      ) : (
        <nav aria-label="Workspace navigation" className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
          {activeWorkspaceSlug ? (
            workspaceRoutes
              .filter(({ access }) => workspaceAuthorization.can(access))
              .map(({ label, suffix, icon: Icon }) => {
                const href = `/org/workspaces/${activeWorkspaceSlug}${suffix}`;
                const isActive = location === href;
                return (
                  <Link
                    key={suffix}
                    href={href}
                    onClick={close}
                    aria-current={isActive ? 'page' : undefined}
                    className={cn(
                      navigationClassName,
                      isActive
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-transparent text-muted-foreground hover:bg-muted hover:text-foreground',
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="truncate">{label}</span>
                  </Link>
                );
              })
          ) : (
            <div className="px-3 py-2 text-xs italic text-muted-foreground">
              {workspaces?.length === 0 ? 'No workspaces in this organization.' : 'Select a workspace above.'}
            </div>
          )}

          <div className="mt-8">
            <div className="mb-2 mt-6 px-3 font-mono text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50">Organization</div>
            {orgRoutes
              .filter(({ access }) => orgAuthorization.can(access))
              .map((item) => {
                const isActive = location === item.path;
                return (
                  <Link
                    key={item.path}
                    href={item.path}
                    onClick={close}
                    aria-current={isActive ? 'page' : undefined}
                    className={cn(
                      navigationClassName,
                      isActive
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-transparent text-muted-foreground hover:bg-muted hover:text-foreground',
                    )}
                  >
                    <item.icon className="h-4 w-4 shrink-0" />
                    {item.label}
                  </Link>
                );
              })}
          </div>
        </nav>
      )}

      <div className="shrink-0 border-t border-border/50 bg-muted/30 p-4">
        <div className="mb-4 flex items-center gap-3 px-1">
          <Avatar aria-hidden="true" className="h-8 w-8">
            <AvatarFallback className="bg-primary/10 text-sm font-bold text-primary">{user?.name?.charAt(0) || '?'}</AvatarFallback>
          </Avatar>
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-sm font-medium leading-tight text-foreground">{user?.name}</span>
            <span className="truncate text-xs text-muted-foreground">{user?.email}</span>
          </div>
        </div>
        <div className="flex items-center justify-between gap-1 px-1">
          <Button variant="ghost" size="sm" onClick={logout} className="h-8 flex-1 justify-start px-2 text-muted-foreground hover:text-destructive">
            <LogOut className="h-4 w-4 shrink-0" />
            Sign out
          </Button>
          {user?.instance_role && (
            <Button asChild variant="ghost" size="icon" className="h-8 w-8 shrink-0 text-muted-foreground hover:text-primary">
              <Link href="/instance" onClick={close} title="Instance console" aria-label="Instance console">
                <Shield className="h-4 w-4" />
              </Link>
            </Button>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <>
      <ResponsiveShell
        brand={<GatewayBrand href="/org" />}
        navigationLabel="Workspace navigation"
        sidebar={sidebar}
        asideClassName="border-border bg-card shadow-sm"
        mainClassName="bg-muted/20"
      >
        {children}
      </ResponsiveShell>

      <FormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New Workspace"
        description="Workspaces group inference keys and members within your organization."
        schema={workspaceNameSchema}
        defaultValues={{ name: '' }}
        onSubmit={async (values) => {
          const created = await createWorkspace.mutateAsync({ orgId, data: values });
          setLocation(`/org/workspaces/${created.slug}`);
        }}
        submitLabel="Create"
        pending={createWorkspace.isPending}
      >
        {(form) => (
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Name</FormLabel>
                <FormControl>
                  <Input placeholder="e.g. production" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        )}
      </FormDialog>
    </>
  );
}
