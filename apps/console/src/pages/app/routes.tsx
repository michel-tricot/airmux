import { lazy, type ComponentType } from 'react';
import { Activity, Boxes, Building2, Settings, type LucideIcon } from 'lucide-react';
import { anyOf, type AccessPolicy } from '@/features/permissions/authorization';
import { catalogAccess } from '@/features/catalog/policy';
import { managementKeyAccess } from '@/features/keys/policy';
import { orgMemberAccess } from '@/features/members/policy';
import { orgAccess } from '@/features/orgs/policy';
import { telemetryAccess } from '@/features/telemetry/policy';

const Dashboard = lazy(() => import('@/pages/app/Dashboard'));
const Requests = lazy(() => import('@/pages/app/Requests'));
const Models = lazy(() => import('@/pages/app/Models'));
const OrgSettings = lazy(() => import('@/pages/app/OrgSettings'));

interface OrgRouteDefinition {
  readonly path: string;
  readonly label: string;
  readonly icon: LucideIcon;
  readonly component: ComponentType;
  readonly access: AccessPolicy;
}

export const orgRoutes: readonly OrgRouteDefinition[] = [
  { path: '/org', label: 'Overview', icon: Building2, component: Dashboard, access: anyOf(orgAccess.read, telemetryAccess.orgUsage) },
  { path: '/org/models', label: 'Models', icon: Boxes, component: Models, access: catalogAccess.org.read },
  { path: '/org/requests', label: 'Requests', icon: Activity, component: Requests, access: telemetryAccess.orgUsage },
  {
    path: '/org/settings',
    label: 'Settings',
    icon: Settings,
    component: OrgSettings,
    access: anyOf(managementKeyAccess.org.read, orgMemberAccess.read, orgMemberAccess.listInvitations, telemetryAccess.orgActivity),
  },
];
