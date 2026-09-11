import { useState } from 'react';
import { Library, Plus } from 'lucide-react';
import type { PolicyOut, RuleOut } from '@workspace/api-client-react';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { ErrorState } from '@/components/shared/states';
import { Button, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/elements';
import { useProviders } from '@/features/credentials/hooks';
import { useInferenceKeys } from '@/features/keys/hooks';
import { useAuthorization } from '@/features/permissions/hooks';
import { usePolicies, usePolicyMutations } from '@/features/policies/hooks';
import { policyAccess } from '@/features/policies/policy';
import { useRuleMutations, useRules } from '@/features/rules/hooks';
import type { RuleKind } from '@/features/rules/types';
import { useRequiredParam } from '@/lib/route';
import { useRequiredOrgId } from '@/lib/session';
import { PolicyEditor } from './PolicyEditor';
import { PolicyTable } from './PolicyTable';
import { RuleEditor } from './RuleEditor';
import { RuleLibrary } from './RuleLibrary';
import { RuleTypePicker } from './RuleTypePicker';

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
  const [editingRuleKind, setEditingRuleKind] = useState<RuleKind | null>(null);
  const [ruleTypeOpen, setRuleTypeOpen] = useState(false);
  const [ruleOpen, setRuleOpen] = useState(false);
  const policyEditorReady = keys.data !== undefined && rules.data !== undefined;
  const ruleEditorReady = catalog.data !== undefined;
  const usageReady = policies.data !== undefined;
  const usageByRuleId = new Map<string, number>();
  for (const policy of policies.data ?? [])
    for (const ruleId of policy.definition.rule_ids) usageByRuleId.set(ruleId, (usageByRuleId.get(ruleId) ?? 0) + 1);

  const editPolicy = (policy: PolicyOut | null) => {
    setEditingPolicy(policy);
    setPolicyOpen(true);
  };
  const createRule = (kind: RuleKind) => {
    setRuleTypeOpen(false);
    setEditingRule(null);
    setEditingRuleKind(kind);
    setRuleOpen(true);
  };
  const editRule = (rule: RuleOut) => {
    setEditingRule(rule);
    setEditingRuleKind(rule.definition.action.kind);
    setRuleOpen(true);
  };

  return (
    <PageShell>
      <PageHeader
        title="Policies"
        description="Build reusable rules once, then attach them to policies that target sets of inference keys."
        actions={
          canManage && (
            <div className="flex gap-2">
              <Button variant="outline" disabled={!ruleEditorReady} onClick={() => setRuleTypeOpen(true)}>
                <Library className="h-4 w-4" />
                Create rule
              </Button>
              <Button disabled={!policyEditorReady} onClick={() => editPolicy(null)}>
                <Plus className="h-4 w-4" />
                Create policy
              </Button>
            </div>
          )
        }
      />
      {canManage && keys.isError && <ErrorState error={keys.error} resource="inference keys" onRetry={() => void keys.refetch()} />}
      {canManage && catalog.isError && <ErrorState error={catalog.error} resource="model catalog" onRetry={() => void catalog.refetch()} />}
      <Tabs defaultValue="policies">
        <TabsList className="mb-4">
          <TabsTrigger value="policies">Policies</TabsTrigger>
          <TabsTrigger value="rules">Rule library</TabsTrigger>
        </TabsList>
        <TabsContent value="rules" className="mt-0">
          <RuleLibrary
            rules={rules.data}
            isLoading={rules.isLoading}
            isError={rules.isError}
            error={rules.error}
            onRetry={() => void rules.refetch()}
            usageByRuleId={usageByRuleId}
            usageReady={usageReady}
            usageLoading={policies.isLoading}
            usageError={policies.isError ? policies.error : undefined}
            onRetryUsage={() => void policies.refetch()}
            canManage={canManage}
            editorReady={ruleEditorReady}
            deletePending={ruleMutations.remove.isPending}
            onEdit={editRule}
            onDelete={(rule) => ruleMutations.remove.mutateAsync({ orgId, workspaceRef, ruleId: rule.id })}
          />
        </TabsContent>
        <TabsContent value="policies" className="mt-0">
          <PolicyTable
            policies={policies.data}
            isLoading={policies.isLoading}
            isError={policies.isError}
            error={policies.error}
            onRetry={() => void policies.refetch()}
            rules={rules.data}
            canManage={canManage}
            editorReady={policyEditorReady}
            isReordering={policyMutations.reorder.isPending}
            onReorder={(policyIds) => policyMutations.reorder.mutateAsync({ orgId, workspaceRef, data: { policy_ids: policyIds } })}
            onEdit={editPolicy}
            onDelete={(policy) => policyMutations.remove.mutateAsync({ orgId, workspaceRef, policyId: policy.id })}
            deletePending={policyMutations.remove.isPending}
          />
        </TabsContent>
      </Tabs>
      {canManage && keys.data && rules.data && (
        <PolicyEditor
          key={editingPolicy ? `${editingPolicy.id}:${editingPolicy.updated_at}` : 'new-policy'}
          policy={editingPolicy}
          open={policyOpen}
          onOpenChange={setPolicyOpen}
          keys={keys.data}
          rules={rules.data}
          pending={policyMutations.create.isPending || policyMutations.update.isPending}
          ruleComposer={
            catalog.data
              ? {
                  catalog: catalog.data,
                  usageByRuleId: usageReady ? usageByRuleId : null,
                  createPending: ruleMutations.create.isPending,
                  updatePending: ruleMutations.update.isPending,
                  create: (data) => ruleMutations.create.mutateAsync({ orgId, workspaceRef, data }),
                  update: (rule, data) => ruleMutations.update.mutateAsync({ orgId, workspaceRef, ruleId: rule.id, data }),
                }
              : undefined
          }
          onSubmit={(data) =>
            editingPolicy
              ? policyMutations.update.mutateAsync({ orgId, workspaceRef, policyId: editingPolicy.id, data })
              : policyMutations.create.mutateAsync({ orgId, workspaceRef, data })
          }
        />
      )}
      {canManage && catalog.data && (
        <>
          <RuleTypePicker open={ruleTypeOpen} onOpenChange={setRuleTypeOpen} onSelect={createRule} />
          {editingRuleKind && (
            <RuleEditor
              rule={editingRule}
              kind={editingRuleKind}
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
        </>
      )}
    </PageShell>
  );
}
