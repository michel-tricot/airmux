import { useRequiredOrgId } from '@/lib/session';
import { useWorkspace } from '@/features/workspaces/hooks';
import { Card } from '@/components/ui/elements';
import { type LucideIcon } from 'lucide-react';
import { useRequiredParam } from '@/lib/route';
import { ErrorState, LoadingState } from '@/components/shared/states';
import { PageShell } from '@/components/shared/page-shell';

function ComingSoonPill() {
  return (
    <span className="inline-flex items-center rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-primary">
      Coming soon
    </span>
  );
}

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
        <ComingSoonPill />
      </div>
      <p className="text-muted-foreground text-sm -mt-4">{workspaceQuery.data ? `Workspace ${workspaceQuery.data.name}` : ''}</p>

      <Card className="p-16 text-center">
        <Icon className="w-12 h-12 mx-auto mb-4 text-muted-foreground opacity-30" />
        <p className="text-muted-foreground">{description}</p>
      </Card>
    </PageShell>
  );
}
