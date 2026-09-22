import { useSearchParams } from 'wouter';
import { SpendingOverview } from '@/components/shared/spending-overview';
import { ErrorState, LoadingState } from '@/components/shared/states';
import { useAuthorization } from '@/features/permissions/hooks';
import { parseOverviewFilters, setOverviewFilter, workspaceOverviewParams } from '@/features/reporting/filters';
import { useWorkspaceOverviewReport } from '@/features/reporting/hooks';
import { telemetryAccess } from '@/features/telemetry/policy';
import { useWorkspace } from '@/features/workspaces/hooks';
import { useRequiredParam } from '@/lib/route';
import { useRequiredOrgId } from '@/lib/session';

export default function WorkspaceOverview() {
  const orgId = useRequiredOrgId();
  const workspaceRef = useRequiredParam('workspaceRef');
  const workspace = useWorkspace(orgId, workspaceRef);
  const authorization = useAuthorization('workspace');
  const authorized = authorization.can(telemetryAccess.workspaceOverview);
  const [search, setSearch] = useSearchParams();
  const filters = parseOverviewFilters(search, Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');
  const report = useWorkspaceOverviewReport(orgId, workspaceRef, workspaceOverviewParams(filters), { enabled: authorized });

  if (workspace.isLoading) return <LoadingState label="Loading workspace..." />;
  if (workspace.isError) return <ErrorState error={workspace.error} resource="workspace" onRetry={() => workspace.refetch()} />;
  if (!workspace.data) return <ErrorState message="Workspace not found" />;

  return (
    <SpendingOverview
      title={workspace.data.name}
      description="Spending and usage for this workspace."
      scope="workspace"
      filters={filters}
      onFilterChange={(name, value) => setSearch(setOverviewFilter(search, name, value), { replace: true })}
      query={report}
      authorized={authorized}
    />
  );
}
