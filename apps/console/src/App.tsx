import { type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
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
import WorkspaceSettings from '@/pages/app/workspace/Settings';
import WorkspaceComingSoon from '@/pages/app/workspace/ComingSoon';
import { Database, Route as RouteIcon, ShieldCheck } from 'lucide-react';

const queryClient = new QueryClient({
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

  if (isLoading) return <Splash>LOADING ORGANIZATIONS...</Splash>;

  // A stored org the user no longer holds would send every org-scoped query on the page to a 403
  // before anything could correct it, so the selection is checked against enrollment first.
  if (!orgId || !enrollment?.orgs.some(o => o.id === orgId)) return <AppOrgPicker />;

  return (
    <AppLayout>
      <Switch>
        <Route path="/app" component={AppDashboard} />
        <Route path="/app/workspaces/:workspaceId/keys" component={WorkspaceApiKeys} />
        <Route path="/app/workspaces/:workspaceId/byok">
          <WorkspaceComingSoon title="BYOK" icon={Database}
            description="Bring your own provider keys and route traffic through them." />
        </Route>
        <Route path="/app/workspaces/:workspaceId/routing">
          <WorkspaceComingSoon title="Routing" icon={RouteIcon}
            description="Model routing rules, fallbacks, and load balancing." />
        </Route>
        <Route path="/app/workspaces/:workspaceId/policies">
          <WorkspaceComingSoon title="Policies" icon={ShieldCheck}
            description="Guardrails, rate limits, and usage policies for this workspace." />
        </Route>
        <Route path="/app/workspaces/:workspaceId/settings" component={WorkspaceSettings} />
        <Route path="/app/workspaces/:workspaceId" component={WorkspaceOverview} />
        <Route path="/app/settings" component={AppOrgSettings} />
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
          <Route path="/" component={Dashboard} />
          <Route path="/organizations" component={Organizations} />
          <Route path="/organizations/:orgId" component={OrganizationDetail} />
          <Route path="/organizations/:orgId/workspaces/:workspaceId" component={WorkspaceDetail} />
          <Route path="/users" component={Users} />
          <Route path="/users/:userId" component={UserDetail} />
          <Route component={NotFound} />
        </Switch>
      </RoutedErrorBoundary>
    </Shell>
  );
}

function Router() {
  const [location] = useLocation();
  const { user, isLoading } = useSession();

  if (isLoading) return <Splash>LOADING SESSION...</Splash>;

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

  if (location.startsWith('/app')) {
    return (
      <RoutedErrorBoundary>
        <AppSection />
      </RoutedErrorBoundary>
    );
  }

  // The instance admin pages run without an org scope, which the control plane grants to
  // instance admins alone; everyone else belongs in their org console.
  if (!user.instance_admin) return <Redirect to="/app" />;

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
