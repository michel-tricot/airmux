import { lazy, Suspense, useEffect, useState, type ComponentType, type ReactNode } from 'react';
import { hashKey, MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { toast } from '@/hooks/use-toast';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import NotFound from '@/pages/not-found';
import { Redirect, Route, Switch, useLocation, Router as WouterRouter } from 'wouter';
import { Shell } from '@/components/layout/Shell';
import '@/lib/api';
import { ApiError } from '@workspace/api-client-react';
import { getEnrollmentQueryKey, getMeQueryKey, useEnrollment } from '@workspace/api-client-react';
import { SessionProvider, useRequiredOrgId, useSession } from '@/lib/session';
import AppLayout from '@/components/layout/AppLayout';
import Login from '@/pages/Login';
import { ErrorState, LoadingState } from '@/components/shared/states';
import { isApiErrorStatus, isControlPlaneUnreachable } from '@/lib/errors';
import { ControlPlaneDown } from '@/components/shared/control-plane-down';
import { AuthorizationProvider, useAuthorization } from '@/features/permissions/hooks';
import type { AccessPolicy } from '@/features/permissions/authorization';
import { workspaceRoutes } from '@/pages/app/workspace/routes';
import { orgRoutes } from '@/pages/app/routes';
import { instanceRoutes } from '@/pages/instance-routes';
import { useRequiredParam } from '@/lib/route';
import { PlaygroundProvider } from '@/features/playground/state';

const CliApprove = lazy(() => import('@/pages/CliApprove'));
const Invite = lazy(() => import('@/pages/Invite'));
const AppOrgPicker = lazy(() => import('@/pages/app/OrgPicker'));

function apiErrorDetail(error: unknown): string | undefined {
  if (!(error instanceof ApiError)) return undefined;
  if (error.status < 400 || error.status >= 500) return undefined;
  const detail = (error.data as { detail?: unknown } | null)?.detail;
  return typeof detail === 'string' && detail.trim() !== '' ? detail : undefined;
}

export function createQueryClient(): QueryClient {
  const meKey = getMeQueryKey();
  const client = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (query.queryHash !== hashKey(meKey)) refreshSession(error);
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        refreshSession(error);
        const meta = mutation.meta as { silentError?: boolean; errorMessage?: string } | undefined;
        if (meta?.silentError) return;
        toast({
          variant: 'destructive',
          title: 'Something went wrong',
          description: apiErrorDetail(error) ?? meta?.errorMessage ?? 'Please try again.',
        });
      },
    }),
    defaultOptions: {
      queries: {
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  });

  function refreshSession(error: unknown) {
    if (isApiErrorStatus(error, 401)) void client.invalidateQueries({ queryKey: meKey, exact: true });
  }

  return client;
}

function AppSection() {
  const { orgId, setOrgId } = useSession();
  const enrollment = useEnrollment({
    query: {
      queryKey: getEnrollmentQueryKey(),
      retry: false,
      refetchOnWindowFocus: 'always',
      refetchInterval: 10_000,
    },
  });

  useEffect(() => {
    if (orgId && enrollment.data && !enrollment.data.orgs.some((org) => org.id === orgId)) setOrgId(null);
  }, [enrollment.data, orgId, setOrgId]);

  if (enrollment.isLoading) return <Splash>Loading organizations...</Splash>;
  if (enrollment.isError || !enrollment.data) {
    return <ErrorState message="Could not load your organizations. Try again." onRetry={() => enrollment.refetch()} />;
  }

  if (!orgId || !enrollment.data.orgs.some((o) => o.id === orgId)) return <Redirect to="/orgs" />;

  return (
    <AuthorizationProvider scope={{ level: 'org', orgId }}>
      <AuthorizedOrgSection orgId={orgId} />
    </AuthorizationProvider>
  );
}

function AuthorizedOrgSection({ orgId }: { orgId: string }) {
  const authorization = useAuthorization('org');
  if (authorization.isLoading) return <LoadingState label="Loading organization permissions..." />;
  if (authorization.isError) {
    return <ErrorState error={authorization.error} resource="organization permissions" onRetry={() => authorization.refetch()} />;
  }
  return (
    <PlaygroundProvider key={orgId}>
      <AppLayout>
        <RoutedErrorBoundary>
          <Suspense fallback={<LoadingState label="Loading page..." />}>
            <Switch>
              {orgRoutes.map(({ path, component, access }) => (
                <Route key={path} path={path}>
                  <AuthorizedRoute component={component} access={access} level="org" />
                </Route>
              ))}
              {workspaceRoutes.map(({ suffix, component, access }) => (
                <Route key={suffix} path={`/org/workspaces/:workspaceRef${suffix}`}>
                  <AuthorizedWorkspaceRoute component={component} access={access} />
                </Route>
              ))}
              <Route component={NotFound} />
            </Switch>
          </Suspense>
        </RoutedErrorBoundary>
      </AppLayout>
    </PlaygroundProvider>
  );
}

function AuthorizedWorkspaceRoute({ component: Component, access }: { component: ComponentType; access: AccessPolicy }) {
  const orgId = useRequiredOrgId();
  const workspaceRef = useRequiredParam('workspaceRef');
  return (
    <AuthorizationProvider scope={{ level: 'workspace', orgId, workspaceRef }}>
      <AuthorizedRoute component={Component} access={access} level="workspace" />
    </AuthorizationProvider>
  );
}

function AuthorizedRoute({
  component: Component,
  access,
  level,
}: {
  component: ComponentType;
  access: AccessPolicy;
  level: 'instance' | 'org' | 'workspace';
}) {
  const authorization = useAuthorization(level);
  const scopeLabel = level === 'org' ? 'organization' : level;
  if (authorization.isLoading) return <LoadingState label={`Loading ${scopeLabel} permissions...`} />;
  if (authorization.isError) {
    return <ErrorState error={authorization.error} resource={`${scopeLabel} permissions`} onRetry={() => authorization.refetch()} />;
  }
  if (!authorization.can(access)) return <ErrorState message={`You do not have access to this ${scopeLabel} page.`} />;
  return <Component />;
}

function AdminSection() {
  return (
    <AuthorizationProvider scope={{ level: 'instance' }}>
      <AuthorizedAdminSection />
    </AuthorizationProvider>
  );
}

function AuthorizedAdminSection() {
  const authorization = useAuthorization('instance');
  if (authorization.isLoading) return <LoadingState label="Loading instance permissions..." />;
  if (authorization.isError) {
    return <ErrorState error={authorization.error} resource="instance permissions" onRetry={() => authorization.refetch()} />;
  }
  return (
    <Shell>
      <RoutedErrorBoundary>
        <Suspense fallback={<LoadingState label="Loading page..." />}>
          <Switch>
            {instanceRoutes.map(({ path, component, access }) => (
              <Route key={path} path={path}>
                <AuthorizedRoute component={component} access={access} level="instance" />
              </Route>
            ))}
            <Route component={NotFound} />
          </Switch>
        </Suspense>
      </RoutedErrorBoundary>
    </Shell>
  );
}

function Router() {
  const [location] = useLocation();
  const { user, isLoading, error, orgId, retry, isRetrying } = useSession();

  if (isLoading) return <Splash>Loading your session...</Splash>;
  if (error && !isApiErrorStatus(error, 401) && isControlPlaneUnreachable(error)) {
    return <ControlPlaneDown onRetry={retry} isRetrying={isRetrying} />;
  }
  if (error && !isApiErrorStatus(error, 401)) {
    return (
      <Splash>
        <ErrorState error={error} resource="session" />
      </Splash>
    );
  }

  if (location === '/invite' || location.startsWith('/invite/')) {
    return (
      <RoutedErrorBoundary>
        <Invite />
      </RoutedErrorBoundary>
    );
  }

  if (!user) return <Login />;

  if (location === '/cli' || location.startsWith('/cli/')) {
    return (
      <RoutedErrorBoundary>
        <CliApprove />
      </RoutedErrorBoundary>
    );
  }

  if (location === '/orgs' || location.startsWith('/orgs/')) {
    return (
      <RoutedErrorBoundary>
        <AppOrgPicker />
      </RoutedErrorBoundary>
    );
  }

  if (location === '/org' || location.startsWith('/org/')) {
    return <AppSection />;
  }

  if (location === '/') return <Redirect to={orgId ? '/org' : '/orgs'} replace />;

  if (!user.instance_role) return <Redirect to="/org" />;

  return <AdminSection />;
}

function Splash({ children }: { children: ReactNode }) {
  return <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30 text-muted-foreground font-mono text-sm">{children}</div>;
}

function RoutedErrorBoundary({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  return <ErrorBoundary resetKey={location}>{children}</ErrorBoundary>;
}

function App() {
  const [client] = useState(createQueryClient);
  return (
    <QueryClientProvider client={client}>
      <SessionProvider>
        <TooltipProvider>
          <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}>
            <Suspense fallback={<Splash>Loading page...</Splash>}>
              <Router />
            </Suspense>
          </WouterRouter>
          <Toaster />
        </TooltipProvider>
      </SessionProvider>
    </QueryClientProvider>
  );
}

export default App;
