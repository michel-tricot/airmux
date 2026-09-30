import { useEffect, useState } from 'react';
import * as z from 'zod';
import { useRequiredOrgId, useSession } from '@/lib/session';
import { useWorkspaces, useCreateWorkspaceMutation } from '@/features/workspaces/hooks';
import { useLocation } from 'wouter';
import { Shield, ArrowLeftRight, Plus } from 'lucide-react';
import { useEnrollment } from '@workspace/api-client-react';
import { Button, Input, Dropdown } from '@/components/ui/elements';
import { ConsoleSidebar, ConsoleNavigationLink, ConsoleNavigationHeading } from '@/components/shared/console-sidebar';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { ErrorState } from '@/components/shared/states';
import { AirmuxBrand, ResponsiveShell } from '@/components/layout/responsive-shell';
import { useAuthorization, useScopedAuthorization } from '@/features/permissions/hooks';
import { workspaceAccess } from '@/features/workspaces/policy';
import { workspaceRoutes } from '@/pages/app/workspace/routes';
import { orgRoutes } from '@/pages/app/routes';

const workspaceNameSchema = z.object({ name: z.string().min(1, 'Name is required') });

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, setOrgId } = useSession();
  const orgId = useRequiredOrgId();
  const orgAuthorization = useAuthorization('org');
  const canListWorkspaces = orgAuthorization.can(workspaceAccess.list);
  const workspacesQuery = useWorkspaces(orgId, { enabled: canListWorkspaces });
  const workspaces = workspacesQuery.data;
  const enrollment = useEnrollment();
  const canSwitchOrg = (enrollment.data?.orgs.length ?? 0) > 1;
  const [location, setLocation] = useLocation();
  const [createOpen, setCreateOpen] = useState(false);

  const match = location.match(/^\/org\/workspaces\/([^/]+)(\/[^/]+)?/);
  const routedWorkspaceRef = match?.[1] ?? '';
  const activeSuffix = match?.[2] ?? '';
  const lastWorkspaceKey = `airmux_last_ws_${orgId}`;
  const selectedWorkspaceRef = routedWorkspaceRef || window.localStorage.getItem(lastWorkspaceKey) || '';
  const activeWorkspace = workspaces?.find((workspace) => workspace.slug === selectedWorkspaceRef || workspace.id === selectedWorkspaceRef);
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
  const switchWorkspace = (slug: string) => setLocation(`/org/workspaces/${slug}${activeSuffix}`);

  const sidebar = (close: () => void) => (
    <ConsoleSidebar
      homeHref="/org"
      onNavigate={close}
      switchConsole={user?.instance_role ? { href: '/instance', label: 'Instance console', icon: Shield } : undefined}
      headerAction={
        canSwitchOrg && (
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
        )
      }
    >
      <div className="shrink-0 border-b border-border/50 p-3">
        <Dropdown
          value={activeWorkspaceSlug}
          onValueChange={(slug) => {
            close();
            switchWorkspace(slug);
          }}
          aria-label="Workspace"
          placeholder={workspacesQuery.isLoading ? 'Loading workspaces...' : 'Select a workspace'}
          disabled={workspacesQuery.isLoading || workspacesQuery.isError}
          className="bg-muted font-medium"
          options={(workspaces ?? []).map((workspace) => ({ value: workspace.slug, label: workspace.name }))}
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
                return <ConsoleNavigationLink key={suffix} href={href} label={label} icon={Icon} active={location === href} onNavigate={close} />;
              })
          ) : (
            <div className="px-3 py-2 text-xs italic text-muted-foreground">
              {workspaces?.length === 0 ? 'No workspaces in this organization.' : 'Select a workspace above.'}
            </div>
          )}

          <div className="mt-8">
            <ConsoleNavigationHeading>Organization</ConsoleNavigationHeading>
            {orgRoutes
              .filter(({ access }) => orgAuthorization.can(access))
              .map((item) => (
                <ConsoleNavigationLink
                  key={item.path}
                  href={item.path}
                  label={item.label}
                  icon={item.icon}
                  active={location === item.path}
                  onNavigate={close}
                />
              ))}
          </div>
        </nav>
      )}
    </ConsoleSidebar>
  );

  return (
    <>
      <ResponsiveShell brand={<AirmuxBrand href="/org" />} navigationLabel="Workspace navigation" sidebar={sidebar}>
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
