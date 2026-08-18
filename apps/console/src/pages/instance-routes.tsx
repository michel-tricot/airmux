import { lazy, type ComponentType } from 'react';
import { Building2, KeyRound, LayoutDashboard, ShieldCheck, Users, type LucideIcon } from 'lucide-react';
import { anyOf, type AccessPolicy } from '@/features/permissions/authorization';
import { accessKeyAccess } from '@/features/keys/policy';
import { providerCredentialAccess } from '@/features/credentials/policy';
import { orgAccess } from '@/features/orgs/policy';
import { telemetryAccess } from '@/features/telemetry/policy';
import { userAccess } from '@/features/users/policy';
import { workspaceAccess } from '@/features/workspaces/policy';

const Dashboard = lazy(() => import('@/pages/Dashboard'));
const Organizations = lazy(() => import('@/pages/Organizations'));
const OrganizationDetail = lazy(() => import('@/pages/OrganizationDetail'));
const WorkspaceDetail = lazy(() => import('@/pages/WorkspaceDetail'));
const UsersPage = lazy(() => import('@/pages/Users'));
const UserDetail = lazy(() => import('@/pages/UserDetail'));
const AccessKeys = lazy(() => import('@/pages/AccessKeys'));
const ProviderKeys = lazy(() => import('@/pages/ProviderKeys'));

export interface InstanceRouteDefinition {
  readonly path: string;
  readonly component: ComponentType;
  readonly access: AccessPolicy;
  readonly navigation?: { readonly label: string; readonly icon: LucideIcon };
}

export const instanceRoutes: readonly InstanceRouteDefinition[] = [
  {
    path: '/instance',
    component: Dashboard,
    access: anyOf(orgAccess.list, userAccess.list, accessKeyAccess.instance.read, telemetryAccess.dataPlanes, telemetryAccess.instanceActivity),
    navigation: { label: 'Overview', icon: LayoutDashboard },
  },
  {
    path: '/instance/organizations',
    component: Organizations,
    access: orgAccess.list,
    navigation: { label: 'Organizations', icon: Building2 },
  },
  { path: '/instance/organizations/:orgId', component: OrganizationDetail, access: orgAccess.read },
  { path: '/instance/organizations/:orgId/workspaces/:workspaceRef', component: WorkspaceDetail, access: workspaceAccess.read },
  {
    path: '/instance/users',
    component: UsersPage,
    access: userAccess.list,
    navigation: { label: 'Users', icon: Users },
  },
  { path: '/instance/users/:userId', component: UserDetail, access: userAccess.read },
  {
    path: '/instance/keys',
    component: AccessKeys,
    access: accessKeyAccess.instance.read,
    navigation: { label: 'Access Keys', icon: KeyRound },
  },
  {
    path: '/instance/provider-keys',
    component: ProviderKeys,
    access: providerCredentialAccess.instance.read,
    navigation: { label: 'Provider Keys', icon: ShieldCheck },
  },
];
