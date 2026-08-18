import { lazy, type ComponentType } from 'react';
import { Database, FlaskConical, KeyRound, LayoutGrid, Route as RouteIcon, Settings, ShieldCheck, type LucideIcon } from 'lucide-react';
import { allOf, anyOf, type AccessPolicy } from '@/features/permissions/authorization';
import { catalogAccess } from '@/features/catalog/policy';
import { providerCredentialAccess } from '@/features/credentials/policy';
import { inferenceKeyAccess } from '@/features/keys/policy';
import { workspaceMemberAccess } from '@/features/members/policy';
import { workspaceAccess } from '@/features/workspaces/policy';
import { playgroundAccess } from '@/features/playground/policy';

const Overview = lazy(() => import('./Overview'));
const Playground = lazy(() => import('./Playground'));
const ApiKeys = lazy(() => import('./ApiKeys'));
const Byok = lazy(() => import('./Byok'));
const SettingsPage = lazy(() => import('./Settings'));
const ComingSoon = lazy(() => import('./ComingSoon'));

interface WorkspaceRouteDefinition {
  readonly suffix: string;
  readonly label: string;
  readonly icon: LucideIcon;
  readonly access: AccessPolicy;
  readonly component: ComponentType;
  readonly soon?: boolean;
}

export const workspaceRoutes: readonly WorkspaceRouteDefinition[] = [
  { suffix: '', label: 'Overview', icon: LayoutGrid, access: workspaceAccess.read, component: Overview },
  {
    suffix: '/playground',
    label: 'Playground',
    icon: FlaskConical,
    access: allOf(catalogAccess.workspace.read, playgroundAccess.execute),
    component: Playground,
  },
  { suffix: '/keys', label: 'Inference Keys', icon: KeyRound, access: inferenceKeyAccess.read, component: ApiKeys },
  { suffix: '/byok', label: 'BYOK', icon: Database, access: providerCredentialAccess.workspace.read, component: Byok },
  {
    suffix: '/routing',
    label: 'Routing',
    icon: RouteIcon,
    access: catalogAccess.workspace.read,
    component: () => <ComingSoon title="Routing" icon={RouteIcon} description="Model routing rules, fallbacks, and load balancing." />,
    soon: true,
  },
  {
    suffix: '/policies',
    label: 'Policies',
    icon: ShieldCheck,
    access: catalogAccess.workspace.read,
    component: () => <ComingSoon title="Policies" icon={ShieldCheck} description="Guardrails, rate limits, and usage policies for this workspace." />,
    soon: true,
  },
  {
    suffix: '/settings',
    label: 'Settings',
    icon: Settings,
    access: anyOf(workspaceMemberAccess.read, workspaceAccess.update, workspaceAccess.delete),
    component: SettingsPage,
  },
];
