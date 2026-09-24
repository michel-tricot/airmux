import { Pencil, Trash2 } from 'lucide-react';
import type { PolicyOut } from '@workspace/api-client-react';
import { DataTable } from '@/components/shared/data-table';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, ConfirmButton } from '@/components/ui/elements';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { RuleActionSummary } from '@/features/rules/presentation';

function RulesSummary({ policy }: { policy: PolicyOut }) {
  const rules = policy.definition.rules;
  const trigger = (
    <Badge
      variant="outline"
      tabIndex={0}
      aria-label={`${rules.length} ${rules.length === 1 ? 'rule' : 'rules'}: ${rules.map((rule) => rule.action.kind).join(', ')}`}
      className="max-w-72 cursor-default normal-case tracking-normal focus:ring-0 focus:ring-offset-0 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      <span className="truncate">
        <RuleActionSummary definition={rules[0]} />
        {rules.length > 1 ? ` +${rules.length - 1} more` : ''}
      </span>
    </Badge>
  );
  return (
    <Tooltip delayDuration={150}>
      <TooltipTrigger asChild>{trigger}</TooltipTrigger>
      <TooltipContent side="bottom" className="pointer-events-none max-w-96 border border-border bg-card p-3 text-foreground shadow-xl">
        <div className="mb-2 font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Rules</div>
        <ul className="space-y-2">
          {rules.map((rule, index) => (
            <li key={`${index}:${rule.action.kind}`}>
              <div className="text-sm font-medium">
                <RuleActionSummary definition={rule} maxVisible={4} />
              </div>
            </li>
          ))}
        </ul>
      </TooltipContent>
    </Tooltip>
  );
}

export function PolicyTable({
  policies,
  isLoading,
  isError,
  error,
  onRetry,
  canManage,
  onBudgetStatus,
  editorReady,
  onEdit,
  onDelete,
  deletePending,
}: {
  policies: PolicyOut[] | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  onRetry: () => void;
  canManage: boolean;
  onBudgetStatus?: (policy: PolicyOut) => void;
  editorReady: boolean;
  onEdit: (policy: PolicyOut) => void;
  onDelete: (policy: PolicyOut) => Promise<unknown>;
  deletePending: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Policies</CardTitle>
      </CardHeader>
      <CardContent>
        <DataTable
          rows={policies}
          rowKey={(policy) => policy.id}
          isLoading={isLoading}
          isError={isError}
          error={error}
          resource="policies"
          onRetry={onRetry}
          empty="No policies configured. Inference uses the workspace's available models and credentials."
          rowClassName="h-16"
          columns={[
            {
              key: 'name',
              header: 'Policy',
              cellClassName: 'w-56 max-w-56',
              cell: (policy) => (
                <div className="min-w-0">
                  <span className="block truncate">{policy.name}</span>
                  <p className="text-xs text-muted-foreground">
                    {policy.definition.rules.length} {policy.definition.rules.length === 1 ? 'rule' : 'rules'}
                  </p>
                </div>
              ),
            },
            {
              key: 'rules',
              header: 'Rules',
              cellClassName: 'w-72 max-w-72',
              cell: (policy) => <RulesSummary policy={policy} />,
            },
            {
              key: 'target',
              header: 'Applies to',
              headClassName: 'min-w-28 whitespace-nowrap',
              cell: (policy) =>
                policy.definition.target.kind === 'workspace'
                  ? 'Workspace'
                  : policy.definition.target.kind === 'selected_users'
                    ? `${policy.definition.target.user_ids.length} selected users`
                    : `${policy.definition.target.key_ids.length} selected keys`,
            },
            {
              key: 'status',
              header: 'Status',
              cell: (policy) => <Badge variant={policy.enabled ? 'success' : 'secondary'}>{policy.enabled ? 'Enabled' : 'Disabled'}</Badge>,
            },
            ...(onBudgetStatus
              ? [
                  {
                    key: 'budgets',
                    header: 'Budgets',
                    cell: (policy: PolicyOut) =>
                      policy.definition.rules.some((rule) => rule.action.kind === 'budget') ? (
                        <Button variant="outline" size="sm" onClick={() => onBudgetStatus(policy)}>
                          View spending
                        </Button>
                      ) : null,
                  },
                ]
              : []),
            ...(canManage
              ? [
                  {
                    key: 'actions',
                    header: 'Actions',
                    cell: (policy: PolicyOut) => (
                      <div className="flex gap-1">
                        <Button size="icon" variant="ghost" disabled={!editorReady} aria-label={`Edit ${policy.name}`} onClick={() => onEdit(policy)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <ConfirmButton
                          title={`Delete ${policy.name}?`}
                          description="This policy will stop applying when gateways adopt the updated configuration."
                          confirmLabel="Delete policy"
                          pending={deletePending}
                          aria-label={`Delete ${policy.name}`}
                          onConfirm={() => onDelete(policy)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </ConfirmButton>
                      </div>
                    ),
                  },
                ]
              : []),
          ]}
        />
      </CardContent>
    </Card>
  );
}
