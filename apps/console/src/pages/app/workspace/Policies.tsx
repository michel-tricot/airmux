import { useState } from 'react';
import { Plus } from 'lucide-react';
import type { PolicyOut } from '@workspace/api-client-react';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { ErrorState } from '@/components/shared/states';
import { Button } from '@/components/ui/elements';
import { useProviders } from '@/features/credentials/hooks';
import { useInferenceKeys } from '@/features/keys/hooks';
import { useAuthorization } from '@/features/permissions/hooks';
import { usePolicies, usePolicyMutations, usePolicyUsers } from '@/features/policies/hooks';
import { policyAccess } from '@/features/policies/policy';
import { useRequiredParam } from '@/lib/route';
import { useRequiredOrgId } from '@/lib/session';
import { PolicyEditor } from './PolicyEditor';
import { PolicyTable } from './PolicyTable';
import { PolicyBudgetDialog } from './PolicyBudgetDialog';

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
  const keys = useInferenceKeys(orgId, workspaceRef, { enabled: canManage });
  const users = usePolicyUsers(orgId, workspaceRef, canManage);
  const catalog = useProviders(orgId, workspaceRef, { enabled: canManage });
  const policyMutations = usePolicyMutations(orgId, workspaceRef);
  const [editingPolicy, setEditingPolicy] = useState<PolicyOut | null>(null);
  const [budgetPolicy, setBudgetPolicy] = useState<PolicyOut | null>(null);
  const [policyOpen, setPolicyOpen] = useState(false);
  const editorReady = keys.data !== undefined && users.data !== undefined && catalog.data !== undefined;

  const editPolicy = (policy: PolicyOut | null) => {
    setEditingPolicy(policy);
    setPolicyOpen(true);
  };

  return (
    <PageShell>
      <PageHeader
        title="Policies"
        description="Define each policy's target, restrictions, and fallbacks in one self-contained resource."
        actions={
          canManage && (
            <Button disabled={!editorReady} onClick={() => editPolicy(null)}>
              <Plus className="h-4 w-4" />
              Create policy
            </Button>
          )
        }
      />
      {canManage && keys.isError && <ErrorState error={keys.error} resource="inference keys" onRetry={() => void keys.refetch()} />}
      {canManage && users.isError && <ErrorState error={users.error} resource="workspace users" onRetry={() => void users.refetch()} />}
      {canManage && catalog.isError && <ErrorState error={catalog.error} resource="model catalog" onRetry={() => void catalog.refetch()} />}
      <PolicyTable
        policies={policies.data}
        isLoading={policies.isLoading}
        isError={policies.isError}
        error={policies.error}
        onRetry={() => void policies.refetch()}
        onBudgetStatus={authorization.can(policyAccess.status) ? setBudgetPolicy : undefined}
        canManage={canManage}
        editorReady={editorReady}
        onEdit={editPolicy}
        onDelete={(policy) => policyMutations.remove.mutateAsync({ orgId, workspaceRef, policyId: policy.id })}
        deletePending={policyMutations.remove.isPending}
      />
      {budgetPolicy && <PolicyBudgetDialog orgId={orgId} workspaceRef={workspaceRef} policy={budgetPolicy} onClose={() => setBudgetPolicy(null)} />}
      {canManage && keys.data && users.data && catalog.data && (
        <PolicyEditor
          key={editingPolicy ? `${editingPolicy.id}:${editingPolicy.updated_at}` : 'new-policy'}
          policy={editingPolicy}
          open={policyOpen}
          onOpenChange={setPolicyOpen}
          keys={keys.data}
          users={users.data}
          catalog={catalog.data}
          pending={policyMutations.create.isPending || policyMutations.update.isPending}
          onSubmit={(data) =>
            editingPolicy
              ? policyMutations.update.mutateAsync({ orgId, workspaceRef, policyId: editingPolicy.id, data })
              : policyMutations.create.mutateAsync({ orgId, workspaceRef, data })
          }
        />
      )}
    </PageShell>
  );
}
