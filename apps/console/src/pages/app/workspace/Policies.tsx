import { type ReactNode, useState } from 'react';
import { closestCenter, DndContext, type DragEndEvent, PointerSensor, TouchSensor, useSensor, useSensors } from '@dnd-kit/core';
import { type AnimateLayoutChanges, arrayMove, SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical, Library, Pencil, Plus, Trash2 } from 'lucide-react';
import type { PolicyOut, RuleOut } from '@workspace/api-client-react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ConfirmButton,
  TableCell,
  TableRow,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/elements';
import { DataTable } from '@/components/shared/data-table';
import { ErrorState } from '@/components/shared/states';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useRequiredOrgId } from '@/lib/session';
import { useRequiredParam } from '@/lib/route';
import { useAuthorization } from '@/features/permissions/hooks';
import { useInferenceKeys } from '@/features/keys/hooks';
import { useProviders } from '@/features/credentials/hooks';
import { usePolicies, usePolicyMutations } from '@/features/policies/hooks';
import { policyAccess } from '@/features/policies/policy';
import { useRuleMutations, useRules } from '@/features/rules/hooks';
import { actionSummary, matchSummary } from '@/features/rules/presentation';
import { cn } from '@/lib/utils';
import { PolicyEditor } from './PolicyEditor';
import { RuleEditor } from './RuleEditor';

const preventPostDropAnimation: AnimateLayoutChanges = () => false;

function SortablePolicyRow({ policy, disabled, children }: { policy: PolicyOut; disabled: boolean; children: ReactNode }) {
  const { isDragging, listeners, setActivatorNodeRef, setNodeRef, transform, transition } = useSortable({
    id: policy.id,
    disabled,
    animateLayoutChanges: preventPostDropAnimation,
  });
  return (
    <TableRow
      ref={setNodeRef}
      className={cn('h-16', isDragging && 'bg-primary/10 opacity-70')}
      style={{ transform: CSS.Translate.toString(transform), transition }}
    >
      <TableCell className="w-12">
        <Button
          size="icon"
          variant="ghost"
          ref={setActivatorNodeRef}
          disabled={disabled}
          aria-label={`Reorder ${policy.name}`}
          className="cursor-grab touch-none text-muted-foreground active:cursor-grabbing"
          {...listeners}
        >
          <GripVertical className="h-4 w-4" />
        </Button>
      </TableCell>
      {children}
    </TableRow>
  );
}

function RulesSummary({ policy, ruleById, dragging }: { policy: PolicyOut; ruleById: Map<string, RuleOut>; dragging: boolean }) {
  const rules = policy.definition.rule_ids
    .map((ruleId) => ({ ruleId, rule: ruleById.get(ruleId) }))
    .sort((left, right) => (left.rule?.name ?? '').localeCompare(right.rule?.name ?? ''));
  const names = rules.map(({ rule }) => rule?.name ?? 'Unavailable rule');
  const summary = `${names[0]}${names.length > 1 ? ` +${names.length - 1} more` : ''}`;
  const trigger = (
    <Badge
      variant="outline"
      tabIndex={0}
      aria-label={`${names.length} ${names.length === 1 ? 'rule' : 'rules'}: ${names.join(', ')}`}
      className="max-w-72 normal-case tracking-normal focus:ring-0 focus:ring-offset-0 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      <span className="truncate">{summary}</span>
    </Badge>
  );
  if (dragging) return trigger;
  return (
    <Tooltip delayDuration={150}>
      <TooltipTrigger asChild>{trigger}</TooltipTrigger>
      <TooltipContent side="bottom" className="pointer-events-none max-w-96 border border-border bg-card p-3 text-foreground shadow-xl">
        <div className="mb-2 font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Rules</div>
        <ul className="space-y-2">
          {rules.map(({ ruleId, rule }) => (
            <li key={ruleId}>
              <p className="text-sm font-medium">{rule?.name ?? 'Unavailable rule'}</p>
              {rule && <p className="text-xs text-muted-foreground">{actionSummary(rule)}</p>}
            </li>
          ))}
        </ul>
      </TooltipContent>
    </Tooltip>
  );
}

function applyOrder(policies: PolicyOut[] | undefined, policyIds: string[] | null): PolicyOut[] | undefined {
  if (!policies || !policyIds) return policies;
  const policiesById = new Map(policies.map((policy) => [policy.id, policy]));
  const orderedPolicies = policyIds.map((policyId) => policiesById.get(policyId));
  return orderedPolicies.every((policy): policy is PolicyOut => policy !== undefined)
    ? orderedPolicies.map((policy, priority) => ({ ...policy, priority }))
    : policies;
}

export default function WorkspacePolicies() {
  const orgId = useRequiredOrgId();
  const workspaceRef = useRequiredParam('workspaceRef');
  return <PoliciesContent key={`${orgId}/${workspaceRef}`} orgId={orgId} workspaceRef={workspaceRef} />;
}

function PoliciesContent({ orgId, workspaceRef }: { orgId: string; workspaceRef: string }) {
  const authorization = useAuthorization('workspace');
  const canRead = authorization.can(policyAccess.read);
  const canManage = authorization.can(policyAccess.manage);
  const policies = usePolicies(orgId, workspaceRef, canRead);
  const rules = useRules(orgId, workspaceRef, canRead);
  const keys = useInferenceKeys(orgId, workspaceRef, { enabled: canManage });
  const catalog = useProviders(orgId, workspaceRef, { enabled: canManage });
  const policyMutations = usePolicyMutations(orgId, workspaceRef);
  const ruleMutations = useRuleMutations(orgId, workspaceRef);
  const [editingPolicy, setEditingPolicy] = useState<PolicyOut | null>(null);
  const [policyOpen, setPolicyOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<RuleOut | null>(null);
  const [ruleOpen, setRuleOpen] = useState(false);
  const [draggedPolicyId, setDraggedPolicyId] = useState<string | null>(null);
  const [pendingPolicyIds, setPendingPolicyIds] = useState<string[] | null>(null);
  const ready = keys.data !== undefined && catalog.data !== undefined && rules.data !== undefined;
  const displayedPolicies = applyOrder(policies.data, pendingPolicyIds);
  const policyIds = displayedPolicies?.map((policy) => policy.id) ?? [];
  const reorderDisabled = policyMutations.reorder.isPending || policyIds.length < 2;
  const ruleById = new Map(rules.data?.map((rule) => [rule.id, rule]));
  const usageByRuleId = new Map<string, number>();
  for (const policy of policies.data ?? [])
    for (const ruleId of policy.definition.rule_ids) usageByRuleId.set(ruleId, (usageByRuleId.get(ruleId) ?? 0) + 1);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 5 } }),
  );
  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    setDraggedPolicyId(null);
    if (!over || active.id === over.id || policyMutations.reorder.isPending) return;
    const from = policyIds.indexOf(String(active.id));
    const to = policyIds.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    const nextPolicyIds = arrayMove(policyIds, from, to);
    setPendingPolicyIds(nextPolicyIds);
    policyMutations.reorder.mutate({ orgId, workspaceRef, data: { policy_ids: nextPolicyIds } }, { onSettled: () => setPendingPolicyIds(null) });
  };

  return (
    <PageShell>
      <PageHeader
        title="Policies"
        description="Build reusable rules once, then attach them to policies that target sets of inference keys."
        actions={
          canManage && (
            <div className="flex gap-2">
              <Button
                variant="outline"
                disabled={catalog.data === undefined}
                onClick={() => {
                  setEditingRule(null);
                  setRuleOpen(true);
                }}
              >
                <Library className="mr-1 h-4 w-4" />
                Create rule
              </Button>
              <Button
                disabled={!ready || !rules.data?.length}
                onClick={() => {
                  setEditingPolicy(null);
                  setPolicyOpen(true);
                }}
              >
                <Plus className="mr-1 h-4 w-4" />
                Create policy
              </Button>
            </div>
          )
        }
      />
      {canManage && keys.isError && <ErrorState error={keys.error} resource="inference keys" onRetry={() => keys.refetch()} />}
      {canManage && catalog.isError && <ErrorState error={catalog.error} resource="model catalog" onRetry={() => catalog.refetch()} />}
      <Tabs defaultValue="policies">
        <TabsList className="mb-4">
          <TabsTrigger value="policies">Policies</TabsTrigger>
          <TabsTrigger value="rules">Rule library</TabsTrigger>
        </TabsList>
        <TabsContent value="rules" className="mt-0">
          <Card>
            <CardHeader>
              <CardTitle>Shared rules</CardTitle>
              <p className="text-sm text-muted-foreground">
                Define a restriction once and use it in any number of policies. Editing it updates every use.
              </p>
            </CardHeader>
            <CardContent>
              <DataTable
                rows={rules.data}
                rowKey={(rule) => rule.id}
                isLoading={rules.isLoading}
                isError={rules.isError}
                error={rules.error}
                resource="rules"
                onRetry={() => void rules.refetch()}
                empty="No shared rules yet. Create a rule before creating a policy."
                columns={[
                  {
                    key: 'name',
                    header: 'Rule',
                    cell: (rule) => (
                      <div>
                        <span>{rule.name}</span>
                        <p className="text-xs text-muted-foreground">When: {matchSummary(rule)}</p>
                      </div>
                    ),
                  },
                  { key: 'action', header: 'Action', cell: actionSummary },
                  {
                    key: 'usage',
                    header: 'Used by',
                    cell: (rule) => {
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
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  disabled={!ready}
                                  aria-label={`Edit ${rule.name}`}
                                  onClick={() => {
                                    setEditingRule(rule);
                                    setRuleOpen(true);
                                  }}
                                >
                                  <Pencil className="h-4 w-4" />
                                </Button>
                                <ConfirmButton
                                  title={`Delete ${rule.name}?`}
                                  description="Unused rules can be deleted permanently."
                                  confirmLabel="Delete rule"
                                  disabled={usage > 0}
                                  pending={ruleMutations.remove.isPending}
                                  aria-label={usage > 0 ? `${rule.name} is used by policies` : `Delete ${rule.name}`}
                                  onConfirm={() => ruleMutations.remove.mutateAsync({ orgId, workspaceRef, ruleId: rule.id })}
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
        </TabsContent>
        <TabsContent value="policies" className="mt-0">
          <Card>
            <CardHeader>
              <CardTitle>Policies</CardTitle>
              {canManage && policyIds.length > 1 && <p className="text-sm text-muted-foreground">Drag policies to change their evaluation order.</p>}
            </CardHeader>
            <CardContent>
              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragStart={({ active }) => setDraggedPolicyId(String(active.id))}
                onDragCancel={() => setDraggedPolicyId(null)}
                onDragEnd={handleDragEnd}
              >
                <SortableContext items={policyIds} strategy={verticalListSortingStrategy}>
                  <DataTable
                    rows={displayedPolicies}
                    rowKey={(policy) => policy.id}
                    isLoading={policies.isLoading}
                    isError={policies.isError}
                    error={policies.error}
                    resource="policies"
                    onRetry={() => void policies.refetch()}
                    empty="No policies configured. Inference uses the workspace's available models and credentials."
                    rowClassName="h-16"
                    renderRow={
                      canManage
                        ? (policy, cells) => (
                            <SortablePolicyRow policy={policy} disabled={reorderDisabled}>
                              {cells.slice(1)}
                            </SortablePolicyRow>
                          )
                        : undefined
                    }
                    columns={[
                      ...(canManage
                        ? [{ key: 'reorder', header: <span className="sr-only">Order</span>, headClassName: 'w-12', cell: () => null }]
                        : []),
                      {
                        key: 'name',
                        header: 'Policy',
                        cellClassName: 'w-56 max-w-56',
                        cell: (policy) => (
                          <div className="min-w-0">
                            <span className="block truncate">{policy.name}</span>
                            <p className="text-xs text-muted-foreground">
                              {policy.definition.rule_ids.length} {policy.definition.rule_ids.length === 1 ? 'rule' : 'rules'}
                            </p>
                          </div>
                        ),
                      },
                      {
                        key: 'rules',
                        header: 'Rules',
                        cellClassName: 'w-72 max-w-72',
                        cell: (policy) => <RulesSummary policy={policy} ruleById={ruleById} dragging={draggedPolicyId !== null} />,
                      },
                      {
                        key: 'target',
                        header: 'Applies to',
                        headClassName: 'min-w-28 whitespace-nowrap',
                        cell: (policy) =>
                          policy.definition.target.kind === 'all_keys' ? 'All keys' : `${policy.definition.target.key_ids.length} selected keys`,
                      },
                      { key: 'priority', header: 'Priority', cell: (policy) => policy.priority },
                      {
                        key: 'status',
                        header: 'Status',
                        cell: (policy) => {
                          const attachedRules = policy.definition.rule_ids
                            .map((id) => ruleById.get(id))
                            .filter((rule): rule is RuleOut => rule !== undefined);
                          return (
                            <Badge variant={policy.enabled ? 'success' : 'secondary'}>
                              {!policy.enabled
                                ? 'Disabled'
                                : attachedRules.length > 0 && attachedRules.every((rule) => rule.definition.action.kind === 'budget')
                                  ? 'Not enforced'
                                  : 'Enabled'}
                            </Badge>
                          );
                        },
                      },
                      ...(canManage
                        ? [
                            {
                              key: 'actions',
                              header: 'Actions',
                              cell: (policy: PolicyOut) => (
                                <div className="flex gap-1">
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    disabled={!ready}
                                    aria-label={`Edit ${policy.name}`}
                                    onClick={() => {
                                      setEditingPolicy(policy);
                                      setPolicyOpen(true);
                                    }}
                                  >
                                    <Pencil className="h-4 w-4" />
                                  </Button>
                                  <ConfirmButton
                                    title={`Delete ${policy.name}?`}
                                    description="This policy will stop applying when gateways adopt the updated configuration."
                                    confirmLabel="Delete policy"
                                    pending={policyMutations.remove.isPending}
                                    aria-label={`Delete ${policy.name}`}
                                    onConfirm={() => policyMutations.remove.mutateAsync({ orgId, workspaceRef, policyId: policy.id })}
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
                </SortableContext>
              </DndContext>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
      {canManage && keys.data && rules.data && (
        <PolicyEditor
          policy={editingPolicy}
          open={policyOpen}
          onOpenChange={setPolicyOpen}
          keys={keys.data}
          rules={rules.data}
          pending={policyMutations.create.isPending || policyMutations.update.isPending}
          onSubmit={(data) =>
            editingPolicy
              ? policyMutations.update.mutateAsync({ orgId, workspaceRef, policyId: editingPolicy.id, data })
              : policyMutations.create.mutateAsync({ orgId, workspaceRef, data })
          }
        />
      )}
      {canManage && catalog.data && (
        <RuleEditor
          rule={editingRule}
          open={ruleOpen}
          onOpenChange={setRuleOpen}
          catalog={catalog.data}
          pending={ruleMutations.create.isPending || ruleMutations.update.isPending}
          onSubmit={(data) =>
            editingRule
              ? ruleMutations.update.mutateAsync({ orgId, workspaceRef, ruleId: editingRule.id, data })
              : ruleMutations.create.mutateAsync({ orgId, workspaceRef, data })
          }
        />
      )}
    </PageShell>
  );
}
