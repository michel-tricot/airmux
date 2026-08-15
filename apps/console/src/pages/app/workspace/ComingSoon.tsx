import { useRequiredOrgId } from '@/lib/session';
import { useWorkspace } from '@/features/workspaces/hooks';
import { Badge, Card } from '@/components/ui/elements';
import { type LucideIcon } from 'lucide-react';
import { useRequiredParam } from '@/lib/route';
import { ErrorState, LoadingState } from '@/components/shared/states';
import { PageShell } from '@/components/shared/page-shell';

export default function WorkspaceComingSoon({ title, description, icon: Icon }: { title: string; description: string; icon: LucideIcon }) {
  const workspaceRef = useRequiredParam('workspaceRef');
  const orgId = useRequiredOrgId();
  const workspaceQuery = useWorkspace(orgId, workspaceRef);

  if (workspaceQuery.isLoading) return <LoadingState label="Loading workspace..." />;
  if (workspaceQuery.isError) return <ErrorState error={workspaceQuery.error} resource="workspace" onRetry={() => workspaceQuery.refetch()} />;

  return (
    <PageShell>
      <div className="flex items-center gap-3">
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        <Badge className="rounded-full">Coming soon</Badge>
      </div>
      <p className="text-muted-foreground text-sm -mt-4">{workspaceQuery.data ? `Workspace ${workspaceQuery.data.name}` : ''}</p>

      <Card className="p-16 text-center">
        <Icon className="w-12 h-12 mx-auto mb-4 text-muted-foreground opacity-30" />
        <p className="text-muted-foreground">{description}</p>
      </Card>
    </PageShell>
  );
}
