import { useSearchParams } from 'wouter';
import { RequestsExplorer } from '@/components/shared/requests-explorer';
import { ErrorState, LoadingState } from '@/components/shared/states';
import { useAuthorization } from '@/features/permissions/hooks';
import { parseRequestFilters, setRequestFilter } from '@/features/reporting/request-filters';
import { telemetryAccess } from '@/features/telemetry/policy';
import { useWorkspace } from '@/features/workspaces/hooks';
import { useRequiredParam } from '@/lib/route';
import { useRequiredOrgId } from '@/lib/session';

export default function Requests() {
  const orgId = useRequiredOrgId();
  const workspaceRef = useRequiredParam('workspaceRef');
  const workspace = useWorkspace(orgId, workspaceRef);
  const authorization = useAuthorization('workspace');
  const authorized = authorization.can(telemetryAccess.workspaceRequests);
  const [search, setSearch] = useSearchParams();
  const filters = parseRequestFilters(search, Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');

  if (workspace.isLoading) return <LoadingState label="Loading workspace..." />;
  if (workspace.isError) return <ErrorState error={workspace.error} resource="workspace" onRetry={() => workspace.refetch()} />;
  if (!workspace.data) return <ErrorState message="Workspace not found" />;

  return (
    <RequestsExplorer
      orgId={orgId}
      workspaceRef={workspaceRef}
      scope="workspace"
      title={`${workspace.data.name} Requests`}
      description="Logical gateway requests, retries, accounting evidence, and exact export for this workspace."
      filters={filters}
      authorized={authorized}
      onFilterChange={(name, value) => setSearch(setRequestFilter(search, name, value), { replace: true })}
    />
  );
}
