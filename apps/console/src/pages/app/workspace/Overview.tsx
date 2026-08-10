import { useParams } from 'wouter';
import { useSession } from '@/lib/session';
import { orgScope } from '@/lib/api';
import {
  useGetWorkspace,
  useListMembers,
  useListInferenceKeys,
  useListEvents,
  getGetWorkspaceQueryKey,
  getListMembersQueryKey,
  getListInferenceKeysQueryKey,
  getListEventsQueryKey,
} from '@workspace/api-client-react';
import { Card, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Badge } from '@/components/ui/elements';
import { TerminalSquare, KeyRound, Users, Database, Activity, Coins, ArrowDownToLine, ArrowUpFromLine } from 'lucide-react';
import { formatRelative } from '@/lib/format';

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
  const { workspaceId } = useParams();
  const { orgId } = useSession();
  const scope = orgScope(orgId!);

  const { data: workspace, isLoading } = useGetWorkspace(workspaceId!, {
    query: { queryKey: [...getGetWorkspaceQueryKey(workspaceId!), orgId], retry: false },
    request: scope,
  });
  const { data: members } = useListMembers(workspaceId!, {
    query: { queryKey: [...getListMembersQueryKey(workspaceId!), orgId] },
    request: scope,
  });
  const { data: keys } = useListInferenceKeys(workspaceId!, {
    query: { queryKey: [...getListInferenceKeysQueryKey(workspaceId!), orgId] },
    request: scope,
  });
  const { data: events } = useListEvents(
    { limit: EVENTS_WINDOW },
    { query: { queryKey: [...getListEventsQueryKey({ limit: EVENTS_WINDOW }), orgId] }, request: scope },
  );

  if (isLoading) return <div className="p-8 text-center text-muted-foreground font-mono text-sm">LOADING WORKSPACE...</div>;
  if (!workspace) return <div className="p-8 text-center text-destructive">Workspace not found</div>;

  const activeKeys = keys?.filter(k => !k.revoked).length;
  const wsEvents = events?.filter(e => e.workspace_id === workspaceId) ?? [];
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
  const topModels = [...byModel.entries()].sort((a, b) => b[1].requests - a[1].requests).slice(0, 5);

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
          <TerminalSquare className="w-6 h-6 text-primary" />
        </div>
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{workspace.name}</h1>
          <p className="text-muted-foreground font-mono text-sm">{workspace.id}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard icon={KeyRound} label="API Keys" value={activeKeys ?? '—'} hint="active inference keys" />
        <MetricCard icon={Users} label="Members" value={members?.length ?? '—'} hint="with workspace access" />
        <MetricCard icon={Database} label="BYOK" value={0} hint="provider keys — coming soon" />
        <MetricCard icon={Activity} label="Requests" value={requests} hint={`in the last ${EVENTS_WINDOW} org events`} />
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
            {topModels.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Model</TableHead>
                    <TableHead className="text-right">Requests</TableHead>
                    <TableHead className="text-right">Tokens</TableHead>
                    <TableHead className="text-right">Cost</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {topModels.map(([model, row]) => (
                    <TableRow key={model}>
                      <TableCell className="font-mono text-xs">{model}</TableCell>
                      <TableCell className="text-right tabular-nums">{row.requests}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatTokens(row.tokens)}</TableCell>
                      <TableCell className="text-right tabular-nums">${row.cost.toFixed(row.cost >= 1 ? 2 : 4)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-8 text-center text-muted-foreground">No usage recorded yet.</div>
            )}
          </Card>
        </div>

        <div className="space-y-3">
          <h2 className="text-lg font-semibold">Recent Activity</h2>
          <Card>
            {recent.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Model</TableHead>
                    <TableHead className="text-right">Tokens</TableHead>
                    <TableHead className="text-right">When</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {recent.map(e => (
                    <TableRow key={e.event_id}>
                      <TableCell className="font-mono text-xs">
                        <Badge variant="outline" className="font-mono">{e.model_id}</Badge>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{formatTokens(e.input_tokens + e.output_tokens)}</TableCell>
                      <TableCell className="text-right text-muted-foreground text-xs">{formatRelative(e.occurred_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-8 text-center text-muted-foreground">No events for this workspace yet.</div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
