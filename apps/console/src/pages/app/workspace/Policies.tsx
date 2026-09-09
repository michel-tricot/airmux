import { type ReactNode, useState } from 'react';
import { closestCenter, DndContext, type DragEndEvent, DragOverlay, PointerSensor, TouchSensor, useSensor, useSensors } from '@dnd-kit/core';
import { arrayMove, SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical, Plus, Pencil, Trash2 } from 'lucide-react';
import type { PolicyOut } from '@workspace/api-client-react';
import { Badge, Button, ConfirmButton, TableCell, TableRow } from '@/components/ui/elements';
import { DataTable } from '@/components/shared/data-table';
import { ErrorState } from '@/components/shared/states';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { useRequiredOrgId } from '@/lib/session';
import { useRequiredParam } from '@/lib/route';
import { useAuthorization } from '@/features/permissions/hooks';
import { useInferenceKeys } from '@/features/keys/hooks';
import { useProviders } from '@/features/credentials/hooks';
import { usePolicies, usePolicyMutations } from '@/features/policies/hooks';
import { policyAccess } from '@/features/policies/policy';
import { cn } from '@/lib/utils';
import { PolicyEditor } from './PolicyEditor';

function SortablePolicyRow({ policy, disabled, children }: { policy: PolicyOut; disabled: boolean; children: ReactNode }) {
  const { isDragging, listeners, setActivatorNodeRef, setNodeRef, transform, transition } = useSortable({ id: policy.id, disabled });
  return (
    <TableRow
      ref={setNodeRef}
      className={cn(isDragging && 'bg-primary/10 opacity-70')}
      style={{ transform: CSS.Transform.toString(transform), transition }}
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

function actionSummary(policy: PolicyOut): string {
  const action = policy.definition.action;
  switch (action.kind) {
    case 'byok':
      return 'Require BYOK';
    case 'models':
      return `Models: ${action.names.join(', ')}`;
    case 'providers':
      return `Providers: ${action.names.join(', ')}`;
    case 'deny':
      return action.message;
    case 'fallback':
      return `Fallback: ${action.models.join(' → ')}`;
    case 'budget':
      return `$${action.amount_usd} / ${action.period} · not enforced`;
  }
}

function matchSummary(policy: PolicyOut): string {
  const match = policy.definition.match;
  if (match.kind === 'all_requests') return 'Every request';
  const criteria = [
    match.models?.length ? `Models: ${match.models.join(', ')}` : '',
    match.stream === true ? 'Streaming' : match.stream === false ? 'Non-streaming' : '',
    match.capabilities?.length ? `Uses: ${match.capabilities.join(', ')}` : '',
  ];
  return criteria.filter(Boolean).join(' · ');
}

export default function WorkspacePolicies() {
  const orgId = useRequiredOrgId();
  const workspaceRef = useRequiredParam('workspaceRef');
  return <PoliciesContent key={`${orgId}/${workspaceRef}`} orgId={orgId} workspaceRef={workspaceRef} />;
}

function PoliciesContent({ orgId, workspaceRef }: { orgId: string; workspaceRef: string }) {
  const authorization = useAuthorization('workspace');
  const canManage = authorization.can(policyAccess.manage);
  const policies = usePolicies(orgId, workspaceRef, authorization.can(policyAccess.read));
  const keys = useInferenceKeys(orgId, workspaceRef, { enabled: canManage });
  const catalog = useProviders(orgId, workspaceRef, { enabled: canManage });
  const { create, update, remove, reorder } = usePolicyMutations(orgId, workspaceRef);
  const [editing, setEditing] = useState<PolicyOut | null>(null);
  const [open, setOpen] = useState(false);
  const [draggedPolicyId, setDraggedPolicyId] = useState<string | null>(null);
  const ready = keys.data !== undefined && catalog.data !== undefined;
  const policyIds = policies.data?.map((policy) => policy.id) ?? [];
  const reorderDisabled = reorder.isPending || policyIds.length < 2;
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 5 } }),
  );
  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    setDraggedPolicyId(null);
    if (!over || active.id === over.id || reorder.isPending) return;
    const from = policyIds.indexOf(String(active.id));
    const to = policyIds.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    reorder.mutate({ orgId, workspaceRef, data: { policy_ids: arrayMove(policyIds, from, to) } });
  };

  return (
    <PageShell>
      <PageHeader
        title="Policies"
        description="Restrict inference and configure model fallbacks for this workspace. All matching restrictions apply."
        actions={
          canManage && (
            <Button
              disabled={!ready}
              onClick={() => {
                setEditing(null);
                setOpen(true);
              }}
            >
              <Plus className="mr-1 h-4 w-4" />
              Create policy
            </Button>
          )
        }
      />
      {canManage && keys.isError && <ErrorState error={keys.error} resource="inference keys" onRetry={() => keys.refetch()} />}
      {canManage && catalog.isError && <ErrorState error={catalog.error} resource="model catalog" onRetry={() => catalog.refetch()} />}
      {canManage && policyIds.length > 1 && <p className="text-xs text-muted-foreground">Drag policies to change their evaluation order.</p>}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragStart={({ active }) => setDraggedPolicyId(String(active.id))}
        onDragCancel={() => setDraggedPolicyId(null)}
        onDragEnd={handleDragEnd}
      >
        <SortableContext items={policyIds} strategy={verticalListSortingStrategy}>
          <DataTable
            rows={policies.data}
            rowKey={(policy) => policy.id}
            isLoading={policies.isLoading}
            isError={policies.isError}
            error={policies.error}
            resource="policies"
            onRetry={() => void policies.refetch()}
            empty="No policies configured. Inference uses the workspace's available models and credentials."
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
                ? [
                    {
                      key: 'reorder',
                      header: <span className="sr-only">Order</span>,
                      headClassName: 'w-12',
                      cell: () => null,
                    },
                  ]
                : []),
              {
                key: 'name',
                header: 'Policy',
                cell: (policy) => (
                  <div>
                    <span>{policy.name}</span>
                    <p className="text-xs text-muted-foreground">When: {matchSummary(policy)}</p>
                  </div>
                ),
              },
              { key: 'action', header: 'Action', cell: actionSummary },
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
                cell: (policy) => (
                  <Badge variant={policy.enabled ? 'success' : 'secondary'}>
                    {!policy.enabled ? 'Disabled' : policy.definition.action.kind === 'budget' ? 'Not enforced' : 'Enabled'}
                  </Badge>
                ),
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
                              setEditing(policy);
                              setOpen(true);
                            }}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <ConfirmButton
                            title={`Delete ${policy.name}?`}
                            description="This policy will stop applying when gateways adopt the updated configuration."
                            confirmLabel="Delete policy"
                            pending={remove.isPending}
                            aria-label={`Delete ${policy.name}`}
                            onConfirm={() => remove.mutateAsync({ orgId, workspaceRef, policyId: policy.id })}
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
        <DragOverlay dropAnimation={null}>
          {draggedPolicyId && (
            <div className="rounded border border-primary/40 bg-card px-4 py-3 text-sm font-medium text-card-foreground shadow-lg shadow-primary/10">
              {policies.data?.find((policy) => policy.id === draggedPolicyId)?.name}
            </div>
          )}
        </DragOverlay>
      </DndContext>
      {canManage && keys.data && catalog.data && (
        <PolicyEditor
          policy={editing}
          open={open}
          onOpenChange={setOpen}
          keys={keys.data}
          catalog={catalog.data}
          pending={create.isPending || update.isPending}
          onSubmit={(data) =>
            editing ? update.mutateAsync({ orgId, workspaceRef, policyId: editing.id, data }) : create.mutateAsync({ orgId, workspaceRef, data })
          }
        />
      )}
    </PageShell>
  );
}
