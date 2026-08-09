import { type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ErrorBoundary } from '@/components/error-boundary';
import { Toaster } from '@/components/ui/toaster';
import { TooltipProvider } from '@/components/ui/tooltip';
import NotFound from '@/pages/not-found';
import {
  Route,
  Switch,
  useLocation,
  Router as WouterRouter,
} from 'wouter';
import { Shell } from '@/components/layout/Shell';

// Admin Pages
import Dashboard from '@/pages/Dashboard';
import Organizations from '@/pages/Organizations';
import OrganizationDetail from '@/pages/OrganizationDetail';
import WorkspaceDetail from '@/pages/WorkspaceDetail';
import Users from '@/pages/Users';
import UserDetail from '@/pages/UserDetail';

// App Pages (Normal User)
import { SessionProvider, useSession } from '@/lib/session';
import AppLayout from '@/components/layout/AppLayout';
import AppLogin from '@/pages/app/Login';
import AppOrgPicker from '@/pages/app/OrgPicker';
import AppDashboard from '@/pages/app/Dashboard';
import AppWorkspaceDetail from '@/pages/app/WorkspaceDetail';
import AppOrgSettings from '@/pages/app/OrgSettings';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function AppSection() {
  const { userId, orgId } = useSession();
  
  if (!userId) return <AppLogin />;
  if (!orgId) return <AppOrgPicker />;
  
  return (
    <AppLayout>
      <Switch>
        <Route path="/app" component={AppDashboard} />
        <Route path="/app/workspaces/:id" component={AppWorkspaceDetail} />
        <Route path="/app/settings" component={AppOrgSettings} />
        <Route component={NotFound} />
      </Switch>
    </AppLayout>
  );
}

function Router() {
  const [location] = useLocation();

  if (location.startsWith('/app')) {
    return (
      <RoutedErrorBoundary>
        <AppSection />
      </RoutedErrorBoundary>
    );
  }

  return (
    <Shell>
      <RoutedErrorBoundary>
        <Switch>
          <Route path="/" component={Dashboard} />
          <Route path="/organizations" component={Organizations} />
          <Route path="/organizations/:id" component={OrganizationDetail} />
          <Route path="/workspaces/:id" component={WorkspaceDetail} />
          <Route path="/users" component={Users} />
          <Route path="/users/:id" component={UserDetail} />
          <Route component={NotFound} />
        </Switch>
      </RoutedErrorBoundary>
    </Shell>
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
