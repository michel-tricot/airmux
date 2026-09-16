import { useState, type ReactNode } from 'react';
import { closestCenter, DndContext, type DragEndEvent, KeyboardSensor, PointerSensor, TouchSensor, useSensor, useSensors } from '@dnd-kit/core';
import {
  type AnimateLayoutChanges,
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical, Pencil, Trash2 } from 'lucide-react';
import type { PolicyOut, RuleOut } from '@workspace/api-client-react';
import { DataTable } from '@/components/shared/data-table';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, ConfirmButton, TableCell, TableRow } from '@/components/ui/elements';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { RuleActionSummary } from '@/features/rules/presentation';
import { cn } from '@/lib/utils';

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
      className="max-w-72 cursor-default normal-case tracking-normal focus:ring-0 focus:ring-offset-0 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
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
              {rule && (
                <div className="text-xs text-muted-foreground">
                  <RuleActionSummary rule={rule} maxVisible={4} />
                </div>
              )}
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

export function PolicyTable({
  policies,
  isLoading,
  isError,
  error,
  onRetry,
  rules,
  canManage,
  editorReady,
  isReordering,
  onReorder,
  onEdit,
  onDelete,
  deletePending,
}: {
  policies: PolicyOut[] | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  onRetry: () => void;
  rules: RuleOut[] | undefined;
  canManage: boolean;
  editorReady: boolean;
  isReordering: boolean;
  onReorder: (policyIds: string[]) => Promise<unknown>;
  onEdit: (policy: PolicyOut) => void;
  onDelete: (policy: PolicyOut) => Promise<unknown>;
  deletePending: boolean;
}) {
  const [draggedPolicyId, setDraggedPolicyId] = useState<string | null>(null);
  const [pendingPolicyIds, setPendingPolicyIds] = useState<string[] | null>(null);
  const displayedPolicies = applyOrder(policies, pendingPolicyIds);
  const policyIds = displayedPolicies?.map((policy) => policy.id) ?? [];
  const reorderDisabled = isReordering || policyIds.length < 2;
  const ruleById = new Map(rules?.map((rule) => [rule.id, rule]));
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const handleDragEnd = async ({ active, over }: DragEndEvent) => {
    setDraggedPolicyId(null);
    if (!over || active.id === over.id || isReordering) return;
    const from = policyIds.indexOf(String(active.id));
    const to = policyIds.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    const nextPolicyIds = arrayMove(policyIds, from, to);
    setPendingPolicyIds(nextPolicyIds);
    await onReorder(nextPolicyIds).catch(() => undefined);
    setPendingPolicyIds(null);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Policies</CardTitle>
        {canManage && policyIds.length > 1 && (
          <p className="text-sm text-muted-foreground">Drag policies or use a reorder handle to change their evaluation order.</p>
        )}
      </CardHeader>
      <CardContent>
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={({ active }) => setDraggedPolicyId(String(active.id))}
          onDragCancel={() => setDraggedPolicyId(null)}
          onDragEnd={(event) => void handleDragEnd(event)}
        >
          <SortableContext items={policyIds} strategy={verticalListSortingStrategy}>
            <DataTable
              rows={displayedPolicies}
              rowKey={(policy) => policy.id}
              isLoading={isLoading}
              isError={isError}
              error={error}
              resource="policies"
              onRetry={onRetry}
              empty="No policies configured. Inference uses the workspace's available models and credentials."
              rowClassName="h-16"
              clipOverflow={draggedPolicyId !== null}
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
                ...(canManage ? [{ key: 'reorder', header: <span className="sr-only">Order</span>, headClassName: 'w-12', cell: () => null }] : []),
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
                    policy.definition.target.kind === 'workspace'
                      ? 'Workspace'
                      : policy.definition.target.kind === 'selected_users'
                        ? `${policy.definition.target.user_ids.length} selected users`
                        : `${policy.definition.target.key_ids.length} selected keys`,
                },
                { key: 'priority', header: 'Priority', cell: (policy) => policy.priority },
                {
                  key: 'status',
                  header: 'Status',
                  cell: (policy) => <Badge variant={policy.enabled ? 'success' : 'secondary'}>{policy.enabled ? 'Enabled' : 'Disabled'}</Badge>,
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
                              disabled={!editorReady}
                              aria-label={`Edit ${policy.name}`}
                              onClick={() => onEdit(policy)}
                            >
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
          </SortableContext>
        </DndContext>
      </CardContent>
    </Card>
  );
}
