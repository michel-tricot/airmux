import { useParams } from 'wouter';
import { useSession } from '@/lib/session';
import { orgScope } from '@/lib/api';
import { useGetWorkspace, getGetWorkspaceQueryKey } from '@workspace/api-client-react';
import { Card } from '@/components/ui/elements';
import { type LucideIcon } from 'lucide-react';

export function ComingSoonPill() {
  return (
    <span className="inline-flex items-center rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-primary">
      Coming soon
    </span>
  );
}

export default function WorkspaceComingSoon({ title, description, icon: Icon }: { title: string; description: string; icon: LucideIcon }) {
  const { workspaceId } = useParams();
  const { orgId } = useSession();
  const { data: workspace } = useGetWorkspace(workspaceId!, {
    query: { queryKey: [...getGetWorkspaceQueryKey(workspaceId!), orgId] },
    request: orgScope(orgId!),
  });

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex items-center gap-3">
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        <ComingSoonPill />
      </div>
      <p className="text-muted-foreground text-sm -mt-4">
        {workspace ? `Workspace ${workspace.name}` : ''}
      </p>

      <Card className="p-16 text-center">
        <Icon className="w-12 h-12 mx-auto mb-4 text-muted-foreground opacity-30" />
        <p className="text-muted-foreground">{description}</p>
      </Card>
    </div>
  );
}
