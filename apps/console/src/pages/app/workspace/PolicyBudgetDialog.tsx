import { useState } from 'react';
import { usePolicyStatus, type KeyBudgetBucket, type PolicyOut, type SharedBudgetBucket } from '@workspace/api-client-react';
import { DataTable } from '@/components/shared/data-table';
import { EmptyState, ErrorState, LoadingState } from '@/components/shared/states';
import { Badge, Button, Dropdown, Input, Label, Modal } from '@/components/ui/elements';
import { formatDate } from '@/lib/format';

type BudgetBucket = SharedBudgetBucket | KeyBudgetBucket;

function bucketId(bucket: BudgetBucket): string {
  if (bucket.kind === 'key') return bucket.key_id;
  return bucket.kind;
}

function bucketLabel(bucket: BudgetBucket): string {
  if (bucket.kind === 'key') return `Key ${bucket.key_id}`;
  return 'All matching usage';
}

export function PolicyBudgetDialog({
  orgId,
  workspaceRef,
  policy,
  onClose,
}: {
  orgId: string;
  workspaceRef: string;
  policy: PolicyOut;
  onClose: () => void;
}) {
  const [ruleIndex, setRuleIndex] = useState(policy.definition.rules.findIndex((rule) => rule.action.kind === 'budget'));
  const [afterBucket, setAfterBucket] = useState<string | undefined>();
  const [bucketIdFilter, setBucketIdFilter] = useState<string | undefined>();
  const [bucketInput, setBucketInput] = useState('');
  const status = usePolicyStatus(orgId, workspaceRef, policy.id, { rule_index: ruleIndex, after_bucket: afterBucket, bucket_id: bucketIdFilter });
  const currentPolicy = status.data?.policy ?? policy;
  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={`${currentPolicy.name}: spending`}
      contentClassName="sm:max-w-2xl"
      description="Observed estimated cost includes matching usage from the whole UTC period. Delivery delays and in-flight requests can exceed the allowance."
    >
      <div className="space-y-4">
        <Dropdown
          aria-label="Budget rule"
          value={String(ruleIndex)}
          onValueChange={(value) => {
            setRuleIndex(Number(value));
            setAfterBucket(undefined);
            setBucketIdFilter(undefined);
            setBucketInput('');
          }}
          options={currentPolicy.definition.rules.flatMap((rule, index) =>
            rule.action.kind === 'budget'
              ? [
                  {
                    value: String(index),
                    label: `Rule ${index + 1}: $${rule.action.amount_usd} / ${rule.action.period} (${rule.action.aggregation.replace('_', ' ')})`,
                  },
                ]
              : [],
          )}
        />
        {currentPolicy.definition.rules[ruleIndex]?.action.kind === 'budget' &&
          currentPolicy.definition.rules[ruleIndex]?.action.aggregation !== 'shared' && (
            <form
              className="flex items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                setBucketIdFilter(bucketInput.trim() || undefined);
                setAfterBucket(undefined);
              }}
            >
              <div className="flex-1 space-y-2">
                <Label htmlFor="budget-bucket">Bucket ID</Label>
                <Input
                  id="budget-bucket"
                  value={bucketInput}
                  onChange={(event) => setBucketInput(event.target.value)}
                  placeholder="All matching buckets"
                />
              </div>
              <Button type="submit" variant="outline">
                Filter
              </Button>
            </form>
          )}
        {status.isLoading ? (
          <LoadingState label="Loading spending..." />
        ) : status.isError ? (
          <ErrorState error={status.error} resource="budget spending" onRetry={() => void status.refetch()} />
        ) : (
          status.data && (
            <>
              {!status.data.policy.enabled && (
                <p className="text-sm text-muted-foreground">This policy is disabled. Usage continues to accumulate.</p>
              )}
              {status.data.budgets.length === 0 && <EmptyState>No budget rules found.</EmptyState>}
              {status.data.budgets.map((budget) => {
                const nextBucket = budget.next_bucket;
                return (
                  <div key={budget.rule_index} className="space-y-3">
                    <p className="text-sm text-muted-foreground">
                      ${budget.amount_usd} allowance · Resets {formatDate(budget.window_end)}
                    </p>
                    <DataTable
                      rows={budget.buckets}
                      rowKey={(entry) => bucketId(entry.bucket)}
                      resource="budget spending"
                      empty="No matching usage in this period."
                      columns={[
                        { key: 'bucket', header: 'Bucket', cell: (entry) => <span className="font-mono text-xs">{bucketLabel(entry.bucket)}</span> },
                        { key: 'spent', header: 'Spent', cell: (entry) => `$${entry.spent_usd}` },
                        { key: 'remaining', header: 'Remaining', cell: (entry) => `$${entry.remaining_usd}` },
                        {
                          key: 'status',
                          header: 'Status',
                          cell: (entry) => (
                            <Badge variant={entry.exhausted ? 'destructive' : 'success'}>{entry.exhausted ? 'Exhausted' : 'Available'}</Badge>
                          ),
                        },
                      ]}
                    />
                    <div className="flex gap-2">
                      {afterBucket && (
                        <Button variant="outline" onClick={() => setAfterBucket(undefined)}>
                          First page
                        </Button>
                      )}
                      {nextBucket && (
                        <Button variant="outline" onClick={() => setAfterBucket(bucketId(nextBucket))}>
                          Next page
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
              <p className="text-xs text-muted-foreground">Calculated {formatDate(status.data.computed_at)}. Recent usage may still be arriving.</p>
            </>
          )
        )}
        <Button variant="outline" disabled={status.isFetching} onClick={() => void status.refetch()}>
          Refresh spending
        </Button>
      </div>
    </Modal>
  );
}
