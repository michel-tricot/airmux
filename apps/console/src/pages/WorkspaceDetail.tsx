import { WorkspacePanel } from '@/components/WorkspacePanel';
import { useRequiredParam } from '@/lib/route';

export default function WorkspaceDetail() {
  const orgId = useRequiredParam('orgId');
  const workspaceRef = useRequiredParam('workspaceRef');

  return (
    <WorkspacePanel
      key={`${orgId}:${workspaceRef}`}
      orgId={orgId}
      workspaceRef={workspaceRef}
      backHref={`/instance/organizations/${orgId}`}
      backLabel="Organization"
    />
  );
}
