import { UsageReporting } from '@/components/shared/usage-reporting';
import { ErrorState, LoadingState } from '@/components/shared/states';
import { useWorkspace } from '@/features/workspaces/hooks';
import { useRequiredParam } from '@/lib/route';
import { useRequiredOrgId } from '@/lib/session';

export default function WorkspaceOverview() {
  const orgId = useRequiredOrgId();
  const workspaceRef = useRequiredParam('workspaceRef');
  const workspace = useWorkspace(orgId, workspaceRef);

  if (workspace.isLoading) return <LoadingState label="Loading workspace..." />;
  if (workspace.isError) return <ErrorState error={workspace.error} resource="workspace" onRetry={() => workspace.refetch()} />;
  if (!workspace.data) return <ErrorState message="Workspace not found" />;

  return <UsageReporting workspaceId={workspace.data.id} workspaceName={workspace.data.name} workspaceRef={workspaceRef} />;
}
