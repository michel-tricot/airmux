import { useRequiredOrgId } from '@/lib/session';
import { useWorkspace } from '@/features/workspaces/hooks';
import { useWorkspaceMembers } from '@/features/members/hooks';
import { useInferenceKeys } from '@/features/keys/hooks';
import { useProviderCredentials } from '@/features/credentials/hooks';
import { useWorkspaceEvents } from '@/features/telemetry/hooks';
import { Card } from '@/components/ui/elements';
import { Badge } from '@/components/ui/elements';
import { TerminalSquare, KeyRound, Users, Database, Activity, Coins, ArrowDownToLine, ArrowUpFromLine } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { LoadingState, ErrorState } from '@/components/shared/states';
import { DataTable } from '@/components/shared/data-table';
import { TokenUsageSource } from '@/components/shared/token-usage-source';
import { useRequiredParam } from '@/lib/route';
import { PageShell } from '@/components/shared/page-shell';
import { useAuthorization } from '@/features/permissions/hooks';
import { providerCredentialAccess } from '@/features/credentials/policy';
import { inferenceKeyAccess } from '@/features/keys/policy';
import { workspaceMemberAccess } from '@/features/members/policy';
import { telemetryAccess } from '@/features/telemetry/policy';
import { formatUsd, sumUsdAmounts } from '@/lib/money';

const EVENTS_WINDOW = 200;

function MetricCard({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: React.ReactNode;
  hint?: string;
}) {
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

const formatTokens = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `${(n / 1_000).toFixed(1)}k` : String(n));

export default function WorkspaceOverview() {
  const workspaceRef = useRequiredParam('workspaceRef');
  const orgId = useRequiredOrgId();

  const workspaceQuery = useWorkspace(orgId, workspaceRef);
  const workspace = workspaceQuery.data;
  const authorization = useAuthorization('workspace');
  const canReadMembers = authorization.can(workspaceMemberAccess.read);
  const canReadKeys = authorization.can(inferenceKeyAccess.read);
  const canReadCredentials = authorization.can(providerCredentialAccess.workspace.read);
  const canReadUsage = authorization.can(telemetryAccess.workspaceUsage);
  const membersQuery = useWorkspaceMembers(orgId, workspaceRef, { enabled: canReadMembers });
  const keysQuery = useInferenceKeys(orgId, workspaceRef, { enabled: canReadKeys });
  const credentialsQuery = useProviderCredentials(orgId, workspaceRef, { enabled: canReadCredentials });
  const eventsQuery = useWorkspaceEvents(orgId, workspaceRef, { limit: EVENTS_WINDOW }, { enabled: workspace !== undefined && canReadUsage });
  const events = eventsQuery.data;

  if (workspaceQuery.isLoading) return <LoadingState label="Loading workspace..." />;
  if (workspaceQuery.isError) return <ErrorState error={workspaceQuery.error} resource="workspace" onRetry={() => workspaceQuery.refetch()} />;
  if (!workspace) return <ErrorState message="Workspace not found" />;

  const activeKeys = keysQuery.data?.filter((key) => !key.revoked).length;
  const requests = events?.length;
  const inputTokens = events?.reduce((sum, event) => sum + event.input_tokens, 0);
  const outputTokens = events?.reduce((sum, event) => sum + event.output_tokens, 0);
  const tokensHint = events?.some((event) => event.token_usage_source === 'estimated')
    ? `latest ${EVENTS_WINDOW} requests, includes estimated counts`
    : `latest ${EVENTS_WINDOW} requests`;
  const costUsd = events ? sumUsdAmounts(events.map((event) => event.cost_usd)) : undefined;
  const recent = events?.slice(0, 8);
  const keyLabels = new Map(keysQuery.data?.map((key) => [key.id, key.label] as const) ?? []);
  const describeKey = (keyId: string) => keyLabels.get(keyId) ?? (canReadKeys && keysQuery.isSuccess ? 'Playground' : null);

  const topModels = events
    ? [...new Set(events.map((event) => event.model_id))]
        .map((model) => {
          const modelEvents = events.filter((event) => event.model_id === model);
          return {
            model,
            requests: modelEvents.length,
            tokens: modelEvents.reduce((sum, event) => sum + event.input_tokens + event.output_tokens, 0),
            tokensEstimated: modelEvents.some((event) => event.token_usage_source === 'estimated'),
            cost: sumUsdAmounts(modelEvents.map((event) => event.cost_usd)),
          };
        })
        .sort((a, b) => b.requests - a.requests)
        .slice(0, 5)
    : undefined;
  const detailsFailed =
    (canReadMembers && membersQuery.isError) || (canReadKeys && keysQuery.isError) || (canReadCredentials && credentialsQuery.isError);

  return (
    <PageShell>
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
          <TerminalSquare className="w-6 h-6 text-primary" />
        </div>
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{workspace.name}</h1>
          <p className="text-muted-foreground font-mono text-sm">{workspace.slug}</p>
        </div>
      </div>

      {detailsFailed && (
        <ErrorState
          message="Some workspace details could not be loaded. Try again."
          onRetry={() =>
            Promise.all([
              ...(canReadMembers ? [membersQuery.refetch()] : []),
              ...(canReadKeys ? [keysQuery.refetch()] : []),
              ...(canReadCredentials ? [credentialsQuery.refetch()] : []),
            ])
          }
        />
      )}

      {(canReadKeys || canReadMembers || canReadCredentials || canReadUsage) && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {canReadKeys && <MetricCard icon={KeyRound} label="Inference Keys" value={activeKeys ?? '-'} hint="active inference keys" />}
          {canReadMembers && <MetricCard icon={Users} label="Members" value={membersQuery.data?.length ?? '-'} hint="with workspace access" />}
          {canReadCredentials && (
            <MetricCard icon={Database} label="BYOK" value={credentialsQuery.data?.length ?? '-'} hint="provider keys configured" />
          )}
          {canReadUsage && <MetricCard icon={Activity} label="Requests" value={requests ?? '-'} hint={`latest ${EVENTS_WINDOW} requests`} />}
        </div>
      )}

      {canReadUsage && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <MetricCard
            icon={ArrowDownToLine}
            label="Input Tokens"
            value={inputTokens === undefined ? '-' : formatTokens(inputTokens)}
            hint={tokensHint}
          />
          <MetricCard
            icon={ArrowUpFromLine}
            label="Output Tokens"
            value={outputTokens === undefined ? '-' : formatTokens(outputTokens)}
            hint={tokensHint}
          />
          <MetricCard
            icon={Coins}
            label="Est. cost"
            value={costUsd === undefined ? '-' : formatUsd(costUsd)}
            hint={`latest ${EVENTS_WINDOW} requests, at catalog prices`}
          />
        </div>
      )}

      {canReadUsage && (
        <div className="grid grid-cols-1 gap-6 items-start">
          <div className="space-y-3">
            <h2 className="text-lg font-semibold">Top Models</h2>
            <Card>
              <DataTable
                rows={topModels}
                rowKey={(row) => row.model}
                isLoading={eventsQuery.isLoading}
                isError={eventsQuery.isError}
                error={eventsQuery.error}
                resource="usage"
                onRetry={() => eventsQuery.refetch()}
                empty="No usage recorded yet."
                columns={[
                  {
                    key: 'model',
                    header: 'Model',
                    cell: (row) => (
                      <Badge variant="outline" className="font-mono">
                        {row.model}
                      </Badge>
                    ),
                  },
                  {
                    key: 'requests',
                    header: 'Requests',
                    headClassName: 'text-right',
                    cellClassName: 'text-right tabular-nums',
                    cell: (row) => row.requests,
                  },
                  {
                    key: 'tokens',
                    header: 'Tokens',
                    headClassName: 'text-right',
                    cellClassName: 'text-right tabular-nums',
                    cell: (row) => `${formatTokens(row.tokens)}${row.tokensEstimated ? ' (estimated)' : ''}`,
                  },
                  {
                    key: 'cost',
                    header: 'Est. cost',
                    headClassName: 'text-right',
                    cellClassName: 'text-right tabular-nums',
                    cell: (row) => formatUsd(row.cost),
                  },
                ]}
              />
            </Card>
          </div>

          <div className="space-y-3">
            <h2 className="text-lg font-semibold">Recent Activity</h2>
            <Card>
              <DataTable
                rows={recent}
                rowKey={(e) => e.event_id}
                isLoading={eventsQuery.isLoading}
                isError={eventsQuery.isError}
                error={eventsQuery.error}
                resource="usage"
                onRetry={() => eventsQuery.refetch()}
                empty="No events for this workspace yet."
                columns={[
                  {
                    key: 'model',
                    header: 'Model',
                    cellClassName: 'font-mono text-xs',
                    cell: (e) => (
                      <Badge variant="outline" className="font-mono">
                        {e.model_id}
                      </Badge>
                    ),
                  },
                  {
                    key: 'key',
                    header: 'Key',
                    cellClassName: 'text-xs',
                    cell: (e) => {
                      const label = describeKey(e.key_id);
                      if (label) return label;
                      if (canReadKeys && keysQuery.isLoading) return <span className="text-muted-foreground">...</span>;
                      return <span className="font-mono text-muted-foreground">{e.key_id}</span>;
                    },
                  },
                  {
                    key: 'tokens',
                    header: 'Tokens',
                    headClassName: 'text-right',
                    cellClassName: 'text-right tabular-nums',
                    cell: (e) => formatTokens(e.input_tokens + e.output_tokens),
                  },
                  {
                    key: 'token_source',
                    header: 'Token source',
                    cell: (e) => <TokenUsageSource source={e.token_usage_source} />,
                  },
                  {
                    key: 'when',
                    header: 'When',
                    headClassName: 'text-right',
                    cellClassName: 'text-right text-muted-foreground text-xs',
                    cell: (e) => formatDate(e.occurred_at),
                  },
                ]}
              />
            </Card>
          </div>
        </div>
      )}
    </PageShell>
  );
}
