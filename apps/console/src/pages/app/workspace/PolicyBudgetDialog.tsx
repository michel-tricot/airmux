import { useState } from 'react';
import { usePolicyStatus, type PolicyOut } from '@workspace/api-client-react';
import { DataTable } from '@/components/shared/data-table';
import { EmptyState, ErrorState, LoadingState } from '@/components/shared/states';
import { Badge, Button, Dropdown, Input, Label, Modal } from '@/components/ui/elements';
import { formatDate } from '@/lib/format';

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
  const [afterKey, setAfterKey] = useState<string | undefined>();
  const [keyId, setKeyId] = useState<string | undefined>();
  const [keyInput, setKeyInput] = useState('');
  const status = usePolicyStatus(orgId, workspaceRef, policy.id, { rule_index: ruleIndex, after_key: afterKey, key_id: keyId });
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
            setAfterKey(undefined);
          }}
          options={currentPolicy.definition.rules.flatMap((rule, index) =>
            rule.action.kind === 'budget'
              ? [
                  {
                    value: String(index),
                    label: `Rule ${index + 1}: $${rule.action.amount_usd} / ${rule.action.period}${rule.action.sharing === 'per_key' ? ' per key' : ' shared'}`,
                  },
                ]
              : [],
          )}
        />
        {currentPolicy.definition.rules[ruleIndex]?.action.kind === 'budget' &&
          currentPolicy.definition.rules[ruleIndex]?.action.sharing === 'per_key' && (
            <form
              className="flex items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                setKeyId(keyInput.trim() || undefined);
                setAfterKey(undefined);
              }}
            >
              <div className="flex-1 space-y-2">
                <Label htmlFor="budget-key">Inference key ID</Label>
                <Input
                  id="budget-key"
                  value={keyInput}
                  onChange={(event) => setKeyInput(event.target.value)}
                  placeholder="All keys with recorded usage"
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
              {status.data.budgets.map((budget) => (
                <div key={budget.rule_index} className="space-y-3">
                  <p className="text-sm text-muted-foreground">
                    ${budget.amount_usd} allowance · Resets {formatDate(budget.window_end)}
                  </p>
                  {budget.sharing === 'shared' ? (
                    <div className="space-y-2">
                      <p>Observed spend: ${budget.spent_usd}</p>
                      <p>Remaining: ${budget.remaining_usd}</p>
                      <Badge variant={budget.exhausted ? 'destructive' : 'success'}>{budget.exhausted ? 'Exhausted' : 'Available'}</Badge>
                    </div>
                  ) : (
                    <>
                      <DataTable
                        rows={budget.keys}
                        rowKey={(key) => key.key_id}
                        resource="key spending"
                        empty="No matching usage in this period."
                        columns={[
                          { key: 'key', header: 'Key', cell: (key) => <span className="font-mono text-xs">{key.key_id}</span> },
                          { key: 'spent', header: 'Spent', cell: (key) => `$${key.spent_usd}` },
                          { key: 'remaining', header: 'Remaining', cell: (key) => `$${key.remaining_usd}` },
                          {
                            key: 'status',
                            header: 'Status',
                            cell: (key) => (
                              <Badge variant={key.exhausted ? 'destructive' : 'success'}>{key.exhausted ? 'Exhausted' : 'Available'}</Badge>
                            ),
                          },
                        ]}
                      />
                      <div className="flex gap-2">
                        {afterKey && (
                          <Button variant="outline" onClick={() => setAfterKey(undefined)}>
                            First page
                          </Button>
                        )}
                        {budget.next_key && (
                          <Button variant="outline" onClick={() => setAfterKey(budget.next_key ?? undefined)}>
                            Next page
                          </Button>
                        )}
                      </div>
                    </>
                  )}
                </div>
              ))}
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
