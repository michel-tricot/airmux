import { useParams } from 'wouter';
import { useSession } from '@/lib/session';
import { useWorkspace } from '@/features/workspaces/hooks';
import { useWorkspaceMembers } from '@/features/members/hooks';
import { useInferenceKeys } from '@/features/keys/hooks';
import { useProviderCredentials } from '@/features/credentials/hooks';
import { useOrgEvents } from '@/features/telemetry/hooks';
import { Card } from '@/components/ui/elements';
import { Badge } from '@/components/ui/elements';
import { TerminalSquare, KeyRound, Users, Database, Activity, Coins, ArrowDownToLine, ArrowUpFromLine } from 'lucide-react';
import { formatRelative } from '@/lib/format';
import { LoadingState, ErrorState } from '@/components/shared/states';
import { DataTable } from '@/components/shared/data-table';

const EVENTS_WINDOW = 200;

function MetricCard({ icon: Icon, label, value, hint }: { icon: React.ComponentType<{ className?: string }>, label: string, value: React.ReactNode, hint?: string }) {
  return (
    <Card className="p-4 flex items-start gap-3">
      <div className="w-9 h-9 rounded-md bg-primary/10 border border-primary/20 flex items-center justify-center shrink-0">
        <Icon className="w-4 h-4 text-primary" />
      </div>
      <div className="min-w-0">
        <div className="text-xs font-mono uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="text-2xl font-bold tracking-tight tabular-nums">{value}</div>
        {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
      </div>
    </Card>
  );
}

const formatTokens = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `${(n / 1_000).toFixed(1)}k` : String(n);

export default function WorkspaceOverview() {
  const { workspaceRef } = useParams();
  const { orgId } = useSession();

  const { data: workspace, isLoading } = useWorkspace(orgId!, workspaceRef!);
  const { data: members } = useWorkspaceMembers(orgId!, workspaceRef!);
  const { data: keys } = useInferenceKeys(orgId!, workspaceRef!);
  const { data: providerCredentials } = useProviderCredentials(orgId!, workspaceRef!);
  const eventsQuery = useOrgEvents(orgId!, { limit: EVENTS_WINDOW });
  const events = eventsQuery.data;

  if (isLoading) return <LoadingState label="Loading workspace..." />;
  if (!workspace) return <ErrorState message="Workspace not found" />;

  const activeKeys = keys?.filter(k => !k.revoked).length;
  const wsEvents = events?.filter(e => e.workspace_id === workspace.id) ?? [];
  const requests = wsEvents.length;
  const inputTokens = wsEvents.reduce((sum, e) => sum + e.input_tokens, 0);
  const outputTokens = wsEvents.reduce((sum, e) => sum + e.output_tokens, 0);
  const costUsd = wsEvents.reduce((sum, e) => sum + e.cost_usd, 0);
  const recent = wsEvents.slice(0, 8);

  const byModel = new Map<string, { requests: number, tokens: number, cost: number }>();
  for (const e of wsEvents) {
    const row = byModel.get(e.model_id) ?? { requests: 0, tokens: 0, cost: 0 };
    row.requests += 1;
    row.tokens += e.input_tokens + e.output_tokens;
    row.cost += e.cost_usd;
    byModel.set(e.model_id, row);
  }
  const topModels = [...byModel.entries()].map(([model, row]) => ({ model, ...row }))
    .sort((a, b) => b.requests - a.requests).slice(0, 5);

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
          <TerminalSquare className="w-6 h-6 text-primary" />
        </div>
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{workspace.name}</h1>
          <p className="text-muted-foreground font-mono text-sm">{workspace.slug}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard icon={KeyRound} label="API Keys" value={activeKeys ?? '—'} hint="active inference keys" />
        <MetricCard icon={Users} label="Members" value={members?.length ?? '—'} hint="with workspace access" />
        <MetricCard icon={Database} label="BYOK" value={providerCredentials?.length ?? '—'} hint="provider keys configured" />
        <MetricCard icon={Activity} label="Requests" value={requests} hint="in recent activity" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <MetricCard icon={ArrowDownToLine} label="Input Tokens" value={formatTokens(inputTokens)} hint="recent usage" />
        <MetricCard icon={ArrowUpFromLine} label="Output Tokens" value={formatTokens(outputTokens)} hint="recent usage" />
        <MetricCard icon={Coins} label="Spend" value={`$${costUsd.toFixed(costUsd >= 1 ? 2 : 4)}`} hint="recent usage" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
        <div className="space-y-3">
          <h2 className="text-lg font-semibold">Top Models</h2>
          <Card>
            <DataTable
              rows={topModels}
              rowKey={row => row.model}
              isError={eventsQuery.isError}
              onRetry={() => eventsQuery.refetch()}
              empty="No usage recorded yet."
              columns={[
                { key: 'model', header: 'Model', cellClassName: 'font-mono text-xs', cell: row => row.model },
                { key: 'requests', header: 'Requests', headClassName: 'text-right', cellClassName: 'text-right tabular-nums', cell: row => row.requests },
                { key: 'tokens', header: 'Tokens', headClassName: 'text-right', cellClassName: 'text-right tabular-nums', cell: row => formatTokens(row.tokens) },
                { key: 'cost', header: 'Cost', headClassName: 'text-right', cellClassName: 'text-right tabular-nums', cell: row => `$${row.cost.toFixed(row.cost >= 1 ? 2 : 4)}` },
              ]}
            />
          </Card>
        </div>

        <div className="space-y-3">
          <h2 className="text-lg font-semibold">Recent Activity</h2>
          <Card>
            <DataTable
              rows={recent}
              rowKey={e => e.event_id}
              isError={eventsQuery.isError}
              onRetry={() => eventsQuery.refetch()}
              empty="No events for this workspace yet."
              columns={[
                {
                  key: 'model',
                  header: 'Model',
                  cellClassName: 'font-mono text-xs',
                  cell: e => <Badge variant="outline" className="font-mono">{e.model_id}</Badge>,
                },
                { key: 'tokens', header: 'Tokens', headClassName: 'text-right', cellClassName: 'text-right tabular-nums', cell: e => formatTokens(e.input_tokens + e.output_tokens) },
                { key: 'when', header: 'When', headClassName: 'text-right', cellClassName: 'text-right text-muted-foreground text-xs', cell: e => formatRelative(e.occurred_at) },
              ]}
            />
          </Card>
        </div>
      </div>
    </div>
  );
}
