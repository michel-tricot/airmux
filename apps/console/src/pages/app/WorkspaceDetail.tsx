import { useParams } from 'wouter';
import { useSession } from '@/lib/session';
import { WorkspacePanel } from '@/components/WorkspacePanel';

export default function AppWorkspaceDetail() {
  const { workspaceId } = useParams();
  const { orgId } = useSession();

  return <WorkspacePanel orgId={orgId!} workspaceId={workspaceId!} backHref="/app" backLabel="Overview" />;
}
