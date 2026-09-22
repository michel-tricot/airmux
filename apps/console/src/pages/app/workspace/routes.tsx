import { lazy, type ComponentType } from 'react';
import { Database, FlaskConical, KeyRound, LayoutGrid, ListTree, Settings, ShieldCheck, type LucideIcon } from 'lucide-react';
import { policyAccess } from '@/features/policies/policy';
import { allOf, anyOf, type AccessPolicy } from '@/features/permissions/authorization';
import { catalogAccess } from '@/features/catalog/policy';
import { providerCredentialAccess } from '@/features/credentials/policy';
import { inferenceKeyAccess, managementKeyAccess } from '@/features/keys/policy';
import { workspaceMemberAccess } from '@/features/members/policy';
import { workspaceAccess } from '@/features/workspaces/policy';
import { playgroundAccess } from '@/features/playground/policy';
import { telemetryAccess } from '@/features/telemetry/policy';

const Overview = lazy(() => import('./Overview'));
const Requests = lazy(() => import('./Requests'));
const Playground = lazy(() => import('./Playground'));
const InferenceKeys = lazy(() => import('./InferenceKeys'));
const Byok = lazy(() => import('./Byok'));
const Policies = lazy(() => import('./Policies'));
const SettingsPage = lazy(() => import('./Settings'));

interface WorkspaceRouteDefinition {
  readonly suffix: string;
  readonly label: string;
  readonly icon: LucideIcon;
  readonly access: AccessPolicy;
  readonly component: ComponentType;
}

export const workspaceRoutes: readonly WorkspaceRouteDefinition[] = [
  { suffix: '', label: 'Overview', icon: LayoutGrid, access: workspaceAccess.read, component: Overview },
  { suffix: '/requests', label: 'Requests', icon: ListTree, access: telemetryAccess.workspaceRequests, component: Requests },
  {
    suffix: '/playground',
    label: 'Playground',
    icon: FlaskConical,
    access: allOf(catalogAccess.workspace.read, playgroundAccess.execute),
    component: Playground,
  },
  { suffix: '/inference-keys', label: 'Inference Keys', icon: KeyRound, access: inferenceKeyAccess.read, component: InferenceKeys },
  { suffix: '/byok', label: 'BYOK', icon: Database, access: providerCredentialAccess.workspace.read, component: Byok },
  { suffix: '/policies', label: 'Policies', icon: ShieldCheck, access: policyAccess.read, component: Policies },
  {
    suffix: '/settings',
    label: 'Settings',
    icon: Settings,
    access: anyOf(workspaceMemberAccess.read, workspaceAccess.update, workspaceAccess.delete, managementKeyAccess.workspace.read),
    component: SettingsPage,
  },
];
