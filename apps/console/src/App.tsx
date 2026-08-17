import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react';
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
import { SessionProvider, useSession } from '@/lib/session';
import AppLayout from '@/components/layout/AppLayout';
import Login from '@/pages/Login';
import { Route as RouteIcon, ShieldCheck } from 'lucide-react';
import { ErrorState, LoadingState } from '@/components/shared/states';
import { isApiErrorStatus, isControlPlaneUnreachable } from '@/lib/errors';
import { ControlPlaneDown } from '@/components/shared/control-plane-down';

const Dashboard = lazy(() => import('@/pages/Dashboard'));
const Organizations = lazy(() => import('@/pages/Organizations'));
const OrganizationDetail = lazy(() => import('@/pages/OrganizationDetail'));
const WorkspaceDetail = lazy(() => import('@/pages/WorkspaceDetail'));
const Users = lazy(() => import('@/pages/Users'));
const UserDetail = lazy(() => import('@/pages/UserDetail'));
const AccessKeys = lazy(() => import('@/pages/AccessKeys'));
const CliApprove = lazy(() => import('@/pages/CliApprove'));
const AppOrgPicker = lazy(() => import('@/pages/app/OrgPicker'));
const AppDashboard = lazy(() => import('@/pages/app/Dashboard'));
const AppModels = lazy(() => import('@/pages/app/Models'));
const AppOrgSettings = lazy(() => import('@/pages/app/OrgSettings'));
const WorkspaceOverview = lazy(() => import('@/pages/app/workspace/Overview'));
const WorkspaceApiKeys = lazy(() => import('@/pages/app/workspace/ApiKeys'));
const WorkspaceByok = lazy(() => import('@/pages/app/workspace/Byok'));
const WorkspaceSettings = lazy(() => import('@/pages/app/workspace/Settings'));
const WorkspaceComingSoon = lazy(() => import('@/pages/app/workspace/ComingSoon'));
const WorkspacePlayground = lazy(() => import('@/pages/app/workspace/Playground'));

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
  const enrollment = useEnrollment({ query: { queryKey: getEnrollmentQueryKey(), retry: false } });

  useEffect(() => {
    if (orgId && enrollment.data && !enrollment.data.orgs.some((org) => org.id === orgId)) setOrgId(null);
  }, [enrollment.data, orgId, setOrgId]);

  if (enrollment.isLoading) return <Splash>Loading organizations...</Splash>;
  if (enrollment.isError || !enrollment.data) {
    return <ErrorState message="Could not load your organizations. Try again." onRetry={() => enrollment.refetch()} />;
  }

  if (!orgId || !enrollment.data.orgs.some((o) => o.id === orgId)) return <Redirect to="/orgs" />;

  return (
    <AppLayout>
      <RoutedErrorBoundary>
        <Suspense fallback={<LoadingState label="Loading page..." />}>
          <Switch>
            <Route path="/org" component={AppDashboard} />
            <Route path="/org/workspaces/:workspaceRef/playground" component={WorkspacePlayground} />
            <Route path="/org/workspaces/:workspaceRef/keys" component={WorkspaceApiKeys} />
            <Route path="/org/workspaces/:workspaceRef/byok" component={WorkspaceByok} />
            <Route path="/org/workspaces/:workspaceRef/routing">
              <WorkspaceComingSoon title="Routing" icon={RouteIcon} description="Model routing rules, fallbacks, and load balancing." />
            </Route>
            <Route path="/org/workspaces/:workspaceRef/policies">
              <WorkspaceComingSoon
                title="Policies"
                icon={ShieldCheck}
                description="Guardrails, rate limits, and usage policies for this workspace."
              />
            </Route>
            <Route path="/org/workspaces/:workspaceRef/settings" component={WorkspaceSettings} />
            <Route path="/org/workspaces/:workspaceRef" component={WorkspaceOverview} />
            <Route path="/org/models" component={AppModels} />
            <Route path="/org/settings" component={AppOrgSettings} />
            <Route component={NotFound} />
          </Switch>
        </Suspense>
      </RoutedErrorBoundary>
    </AppLayout>
  );
}

function AdminSection() {
  return (
    <Shell>
      <RoutedErrorBoundary>
        <Suspense fallback={<LoadingState label="Loading page..." />}>
          <Switch>
            <Route path="/instance" component={Dashboard} />
            <Route path="/instance/organizations" component={Organizations} />
            <Route path="/instance/organizations/:orgId" component={OrganizationDetail} />
            <Route path="/instance/organizations/:orgId/workspaces/:workspaceRef" component={WorkspaceDetail} />
            <Route path="/instance/users" component={Users} />
            <Route path="/instance/users/:userId" component={UserDetail} />
            <Route path="/instance/keys" component={AccessKeys} />
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
