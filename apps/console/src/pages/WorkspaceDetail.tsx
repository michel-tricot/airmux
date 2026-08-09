import { useParams } from 'wouter';
import { WorkspacePanel } from '@/components/WorkspacePanel';

export default function WorkspaceDetail() {
  const { orgId, workspaceId } = useParams();

  return (
    <WorkspacePanel
      orgId={orgId!}
      workspaceId={workspaceId!}
      backHref={`/organizations/${orgId}`}
      backLabel="Organization"
    />
  );
}
