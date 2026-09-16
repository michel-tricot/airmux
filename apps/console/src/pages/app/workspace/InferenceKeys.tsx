import { InferenceKeyDialog } from '@/components/shared/inference-key-dialog';
import { useState } from 'react';
import { useRequiredOrgId } from '@/lib/session';
import { useInferenceKeys, useRevokeInferenceKeyMutation } from '@/features/keys/hooks';
import { Button } from '@/components/ui/elements';
import { Plus } from 'lucide-react';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { KeysTable } from '@/components/shared/keys-table';
import { useRequiredParam } from '@/lib/route';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { useAuthorization } from '@/features/permissions/hooks';
import { inferenceKeyAccess } from '@/features/keys/policy';
import type { InferenceKeyOut } from '@workspace/api-client-react';
import { usePolicies } from '@/features/policies/hooks';
import { policyAccess } from '@/features/policies/policy';
import { ErrorState } from '@/components/shared/states';
import { Modal, Badge } from '@/components/ui/elements';

export default function WorkspaceInferenceKeys() {
  const workspaceRef = useRequiredParam('workspaceRef');
  const orgId = useRequiredOrgId();

  const authorization = useAuthorization('workspace');
  const canRead = authorization.can(inferenceKeyAccess.read);
  const canCreate = authorization.can(inferenceKeyAccess.create);
  const canRevoke = authorization.can(inferenceKeyAccess.revoke);
  const keysQuery = useInferenceKeys(orgId, workspaceRef, { enabled: canRead });
  const canReadPolicies = authorization.can(policyAccess.read);
  const policies = usePolicies(orgId, workspaceRef, canReadPolicies);
  const [inspectingKey, setInspectingKey] = useState<InferenceKeyOut | null>(null);
  const applicablePolicies = (key: InferenceKeyOut) =>
    (policies.data ?? []).filter((policy) => {
      const target = policy.definition.target;
      return (
        policy.enabled &&
        policy.workspace_id === key.workspace_id &&
        (target.kind === 'workspace' || (target.kind === 'selected_users' ? target.user_ids.includes(key.user_id) : target.key_ids.includes(key.id)))
      );
    });

  const [keyOpen, setKeyOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  const revokeKey = useRevokeInferenceKeyMutation(orgId, workspaceRef);

  return (
    <PageShell>
      <PageHeader
        title="Inference Keys"
        description="Keys let applications send requests to the models available to this workspace."
        actions={
          canCreate && (
            <Button onClick={() => setKeyOpen(true)}>
              <Plus className="w-4 h-4" /> Generate Key
            </Button>
          )
        }
      />

      {canReadPolicies && policies.isError && <ErrorState error={policies.error} resource="policies" onRetry={() => void policies.refetch()} />}
      <KeysTable
        resource="inference keys"
        keys={keysQuery.data}
        isLoading={keysQuery.isLoading}
        isError={keysQuery.isError}
        error={keysQuery.error}
        onRetry={() => keysQuery.refetch()}
        emptyText="No inference keys generated."
        extraColumns={
          canReadPolicies
            ? [
                {
                  key: 'policies',
                  header: 'Policies',
                  cell: (key) => (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={policies.data === undefined}
                      aria-label={`Inspect policies for ${key.label}`}
                      onClick={() => setInspectingKey(key)}
                    >
                      {policies.data === undefined ? 'Unavailable' : `${applicablePolicies(key).length} applicable`}
                    </Button>
                  ),
                },
              ]
            : []
        }
        revokeDescription="Requests using this inference key will stop working immediately. This cannot be undone."
        onRevoke={canRevoke ? (key) => revokeKey.mutateAsync({ orgId, workspaceRef, keyId: key.id }) : undefined}
        revokePending={canRevoke ? revokeKey.isPending : undefined}
      />

      {canCreate && <InferenceKeyDialog orgId={orgId} workspaceRef={workspaceRef} open={keyOpen} onOpenChange={setKeyOpen} onCreated={setToken} />}

      <KeyRevealDialog open={!!token} onOpenChange={(v) => !v && setToken(null)} token={token} />
      <Modal
        open={inspectingKey !== null}
        onOpenChange={(open) => !open && setInspectingKey(null)}
        title={`Policies for ${inspectingKey?.label ?? 'key'}`}
        description="All applicable restrictions compose. Request conditions determine which rules apply to each request."
      >
        {inspectingKey && (
          <div className="space-y-3">
            {applicablePolicies(inspectingKey).length === 0 && <p className="text-sm text-muted-foreground">No applicable policies.</p>}
            {applicablePolicies(inspectingKey).map((policy) => (
              <div key={policy.id} className="flex items-center justify-between gap-3">
                <span>{policy.name}</span>
                <Badge variant="outline">
                  {policy.definition.target.kind === 'workspace' ? 'Workspace' : policy.definition.target.kind === 'selected_users' ? 'User' : 'Key'}
                </Badge>
              </div>
            ))}
          </div>
        )}
      </Modal>
    </PageShell>
  );
}
