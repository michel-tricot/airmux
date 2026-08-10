import { type ReactNode } from 'react';
import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { toast } from '@/hooks/use-toast';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import NotFound from '@/pages/not-found';
import {
  Redirect,
  Route,
  Switch,
  useLocation,
  Router as WouterRouter,
} from 'wouter';
import { Shell } from '@/components/layout/Shell';
import '@/lib/api';
import { ApiError } from '@workspace/api-client-react';

// Instance Admin Pages
import Dashboard from '@/pages/Dashboard';
import Organizations from '@/pages/Organizations';
import OrganizationDetail from '@/pages/OrganizationDetail';
import WorkspaceDetail from '@/pages/WorkspaceDetail';
import Users from '@/pages/Users';
import UserDetail from '@/pages/UserDetail';

// Org Pages (Any Member)
import { useEnrollment } from '@workspace/api-client-react';
import { SessionProvider, useSession } from '@/lib/session';
import AppLayout from '@/components/layout/AppLayout';
import Login from '@/pages/Login';
import CliApprove from '@/pages/CliApprove';
import AppOrgPicker from '@/pages/app/OrgPicker';
import AppDashboard from '@/pages/app/Dashboard';
import AppOrgSettings from '@/pages/app/OrgSettings';
import WorkspaceOverview from '@/pages/app/workspace/Overview';
import WorkspaceApiKeys from '@/pages/app/workspace/ApiKeys';
import WorkspaceByok from '@/pages/app/workspace/Byok';
import WorkspaceSettings from '@/pages/app/workspace/Settings';
import WorkspaceComingSoon from '@/pages/app/workspace/ComingSoon';
import { Route as RouteIcon, ShieldCheck } from 'lucide-react';

/**
 * The control plane refuses some actions with a specific reason (e.g. "User still
 * belongs to 2 organizations") in the response's `detail`. Surface that string for
 * client errors so the toast is actionable; validation errors put an array there
 * and server errors carry nothing useful, so those fall back to the generic copy.
 */
function apiErrorDetail(error: unknown): string | undefined {
  if (!(error instanceof ApiError)) return undefined;
  if (error.status < 400 || error.status >= 500) return undefined;
  const detail = (error.data as { detail?: unknown } | null)?.detail;
  return typeof detail === 'string' && detail.trim() !== '' ? detail : undefined;
}

export const queryClient = new QueryClient({
  // Every mutation surfaces its failure as a toast unless it opts out
  // (meta.silentError) to render the error inline, e.g. the login form.
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
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

function AppSection() {
  const { orgId } = useSession();
  const { data: enrollment, isLoading } = useEnrollment();

  if (isLoading) return <Splash>Loading organizations...</Splash>;

  // A stored org the user no longer holds would send every org-scoped query on the page to a 403
  // before anything could correct it, so the selection is checked against enrollment first.
  if (!orgId || !enrollment?.orgs.some(o => o.id === orgId)) return <Redirect to="/orgs" />;

  return (
    <AppLayout>
      <Switch>
        <Route path="/org" component={AppDashboard} />
        <Route path="/org/workspaces/:workspaceRef/keys" component={WorkspaceApiKeys} />
        <Route path="/org/workspaces/:workspaceRef/byok" component={WorkspaceByok} />
        <Route path="/org/workspaces/:workspaceRef/routing">
          <WorkspaceComingSoon title="Routing" icon={RouteIcon}
            description="Model routing rules, fallbacks, and load balancing." />
        </Route>
        <Route path="/org/workspaces/:workspaceRef/policies">
          <WorkspaceComingSoon title="Policies" icon={ShieldCheck}
            description="Guardrails, rate limits, and usage policies for this workspace." />
        </Route>
        <Route path="/org/workspaces/:workspaceRef/settings" component={WorkspaceSettings} />
        <Route path="/org/workspaces/:workspaceRef" component={WorkspaceOverview} />
        <Route path="/org/settings" component={AppOrgSettings} />
        <Route component={NotFound} />
      </Switch>
    </AppLayout>
  );
}

function AdminSection() {
  return (
    <Shell>
      <RoutedErrorBoundary>
        <Switch>
          <Route path="/instance" component={Dashboard} />
          <Route path="/instance/organizations" component={Organizations} />
          <Route path="/instance/organizations/:orgId" component={OrganizationDetail} />
          <Route path="/instance/organizations/:orgId/workspaces/:workspaceRef" component={WorkspaceDetail} />
          <Route path="/instance/users" component={Users} />
          <Route path="/instance/users/:userId" component={UserDetail} />
          <Route component={NotFound} />
        </Switch>
      </RoutedErrorBoundary>
    </Shell>
  );
}

function Router() {
  const [location] = useLocation();
  const { user, isLoading, orgId } = useSession();

  if (isLoading) return <Splash>Loading your session...</Splash>;

  if (!user) return <Login />;

  // Where `airllm login` sends the browser. Any signed-in account can approve its own device
  // login, so this sits ahead of the instance-admin gate rather than inside either console.
  if (location.startsWith('/cli')) {
    return (
      <RoutedErrorBoundary>
        <CliApprove />
      </RoutedErrorBoundary>
    );
  }

  // /orgs is the full-page org picker; /org/... is the console scoped to the selected org.
  if (location === '/orgs' || location.startsWith('/orgs/')) {
    return (
      <RoutedErrorBoundary>
        <AppOrgPicker />
      </RoutedErrorBoundary>
    );
  }

  if (location === '/org' || location.startsWith('/org/')) {
    return (
      <RoutedErrorBoundary>
        <AppSection />
      </RoutedErrorBoundary>
    );
  }

  // Fresh sign-ins land at the root: send them to the last-selected org, or the
  // picker when none is remembered. (An invalid remembered org still falls back
  // to the picker via the enrollment check in AppSection.)
  if (location === '/') return <Redirect to={orgId ? '/org' : '/orgs'} replace />;

  // The instance admin pages run without an org scope, which the control plane grants to
  // instance admins alone; everyone else belongs in their org console.
  if (!user.instance_admin) return <Redirect to="/org" />;

  return <AdminSection />;
}

function Splash({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30 text-muted-foreground font-mono text-sm">
      {children}
    </div>
  );
}

function RoutedErrorBoundary({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  return <ErrorBoundary resetKey={location}>{children}</ErrorBoundary>;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <TooltipProvider>
          <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}>
            <Router />
          </WouterRouter>
          <Toaster />
        </TooltipProvider>
      </SessionProvider>
    </QueryClientProvider>
  );
}

export default App;
