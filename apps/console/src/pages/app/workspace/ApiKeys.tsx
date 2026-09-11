import { InferenceKeyDialog } from '@/components/shared/inference-key-dialog';
import { useState } from 'react';
import { useRequiredOrgId } from '@/lib/session';
import { useInferenceKeys, useRevokeInferenceKeyMutation } from '@/features/keys/hooks';
import { Button } from '@/components/ui/elements';
import { Plus } from 'lucide-react';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { ApiKeysTable } from '@/components/shared/api-keys-table';
import { useRequiredParam } from '@/lib/route';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { useAuthorization } from '@/features/permissions/hooks';
import { inferenceKeyAccess } from '@/features/keys/policy';

export default function WorkspaceApiKeys() {
  const workspaceRef = useRequiredParam('workspaceRef');
  const orgId = useRequiredOrgId();

  const authorization = useAuthorization('workspace');
  const canRead = authorization.can(inferenceKeyAccess.read);
  const canCreate = authorization.can(inferenceKeyAccess.create);
  const canRevoke = authorization.can(inferenceKeyAccess.revoke);
  const keysQuery = useInferenceKeys(orgId, workspaceRef, { enabled: canRead });

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
              <Plus className="w-4 h-4 mr-1" /> Generate Key
            </Button>
          )
        }
      />

      <ApiKeysTable
        resource="inference keys"
        keys={keysQuery.data}
        isLoading={keysQuery.isLoading}
        isError={keysQuery.isError}
        error={keysQuery.error}
        onRetry={() => keysQuery.refetch()}
        emptyText="No inference keys generated."
        revokeDescription="Requests using this inference key will stop working immediately. This cannot be undone."
        onRevoke={canRevoke ? (key) => revokeKey.mutateAsync({ orgId, workspaceRef, keyId: key.id }) : undefined}
        revokePending={canRevoke ? revokeKey.isPending : undefined}
      />

      {canCreate && <InferenceKeyDialog orgId={orgId} workspaceRef={workspaceRef} open={keyOpen} onOpenChange={setKeyOpen} onCreated={setToken} />}

      <KeyRevealDialog open={!!token} onOpenChange={(v) => !v && setToken(null)} token={token} />
    </PageShell>
  );
}
