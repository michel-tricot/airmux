import { useParams } from 'wouter';
import { WorkspacePanel } from '@/components/WorkspacePanel';

export default function WorkspaceDetail() {
  const { orgId, workspaceRef } = useParams();

  return (
    <WorkspacePanel
      orgId={orgId!}
      workspaceRef={workspaceRef!}
      backHref={`/instance/organizations/${orgId}`}
      backLabel="Organization"
    />
  );
}
