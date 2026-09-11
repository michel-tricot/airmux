import { Pencil, Trash2 } from 'lucide-react';
import type { RuleOut } from '@workspace/api-client-react';
import { DataTable } from '@/components/shared/data-table';
import { ErrorState } from '@/components/shared/states';
import { Button, Card, CardContent, CardHeader, CardTitle, ConfirmButton } from '@/components/ui/elements';
import { RuleActionSummary, RuleMatchSummary } from '@/features/rules/presentation';

export function RuleLibrary({
  rules,
  isLoading,
  isError,
  error,
  onRetry,
  usageByRuleId,
  usageReady,
  usageLoading,
  usageError,
  onRetryUsage,
  canManage,
  editorReady,
  deletePending,
  onEdit,
  onDelete,
}: {
  rules: RuleOut[] | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  onRetry: () => void;
  usageByRuleId: Map<string, number>;
  usageReady: boolean;
  usageLoading: boolean;
  usageError: unknown;
  onRetryUsage: () => void;
  canManage: boolean;
  editorReady: boolean;
  deletePending: boolean;
  onEdit: (rule: RuleOut) => void;
  onDelete: (rule: RuleOut) => Promise<unknown>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Shared rules</CardTitle>
        <p className="text-sm text-muted-foreground">Define a restriction once and use it in any number of policies. Editing it updates every use.</p>
      </CardHeader>
      <CardContent>
        {usageError !== undefined && !usageReady && (
          <ErrorState message="Usage unavailable" error={usageError} onRetry={onRetryUsage} className="px-0 pt-0" />
        )}
        <DataTable
          rows={rules}
          rowKey={(rule) => rule.id}
          isLoading={isLoading}
          isError={isError}
          error={error}
          resource="rules"
          onRetry={onRetry}
          empty="No shared rules yet. Create a rule before creating a policy."
          columns={[
            {
              key: 'name',
              header: 'Rule',
              cell: (rule) => (
                <div>
                  <span>{rule.name}</span>
                  <div className="text-xs text-muted-foreground">
                    When: <RuleMatchSummary rule={rule} />
                  </div>
                </div>
              ),
            },
            { key: 'action', header: 'Action', cell: (rule) => <RuleActionSummary rule={rule} /> },
            {
              key: 'usage',
              header: 'Used by',
              cell: (rule) => {
                if (!usageReady) return usageLoading ? 'Loading usage…' : 'Unavailable';
                const usage = usageByRuleId.get(rule.id) ?? 0;
                return `${usage} ${usage === 1 ? 'policy' : 'policies'}`;
              },
            },
            ...(canManage
              ? [
                  {
                    key: 'actions',
                    header: 'Actions',
                    cell: (rule: RuleOut) => {
                      const usage = usageByRuleId.get(rule.id) ?? 0;
                      return (
                        <div className="flex gap-1">
                          <Button size="icon" variant="ghost" disabled={!editorReady} aria-label={`Edit ${rule.name}`} onClick={() => onEdit(rule)}>
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <ConfirmButton
                            title={`Delete ${rule.name}?`}
                            description="Unused rules can be deleted permanently."
                            confirmLabel="Delete rule"
                            disabled={!usageReady || usage > 0}
                            pending={deletePending}
                            aria-label={
                              !usageReady
                                ? `${rule.name} usage is unavailable`
                                : usage > 0
                                  ? `${rule.name} is used by policies`
                                  : `Delete ${rule.name}`
                            }
                            onConfirm={() => onDelete(rule)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </ConfirmButton>
                        </div>
                      );
                    },
                  },
                ]
              : []),
          ]}
        />
      </CardContent>
    </Card>
  );
}
