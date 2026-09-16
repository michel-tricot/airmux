import { WorkspaceManagementKeys } from '@/components/shared/workspace-management-keys';
import { InferenceKeyDialog } from '@/components/shared/inference-key-dialog';
import { useState } from 'react';
import * as z from 'zod';
import { Button, Input, Badge, ConfirmButton, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/elements';
import { TerminalSquare, Plus, ArrowLeft, Key, Users, Pencil, Trash2 } from 'lucide-react';
import { Link, useLocation } from 'wouter';
import { useWorkspace, useRenameWorkspaceMutation, useDeleteWorkspaceMutation } from '@/features/workspaces/hooks';
import { useInferenceKeys, useRevokeInferenceKeyMutation } from '@/features/keys/hooks';
import { LoadingState, ErrorState } from '@/components/shared/states';
import { FormDialog } from '@/components/shared/form-dialog';
import { WorkspaceMembersPanel } from '@/components/shared/workspace-members-panel';
import { KeysTable } from '@/components/shared/keys-table';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { PageShell } from '@/components/shared/page-shell';
import { useScopedAuthorization } from '@/features/permissions/hooks';
import { inferenceKeyAccess, managementKeyAccess } from '@/features/keys/policy';
import { workspaceMemberAccess } from '@/features/members/policy';
import { workspaceAccess } from '@/features/workspaces/policy';
import { useSession } from '@/lib/session';

const nameSchema = z.object({ name: z.string().min(1, 'Name is required') });

interface WorkspacePanelProps {
  orgId: string;
  workspaceRef: string;
  backHref: string;
  backLabel: string;
}

export function WorkspacePanel({ orgId, workspaceRef, backHref, backLabel }: WorkspacePanelProps) {
  const [, setLocation] = useLocation();
  const { user } = useSession();

  const authorization = useScopedAuthorization({ level: 'workspace', orgId, workspaceRef });
  const canReadWorkspace = authorization.can(workspaceAccess.read);
  const workspaceQuery = useWorkspace(orgId, workspaceRef, { enabled: canReadWorkspace });
  const workspace = workspaceQuery.data;
  const canReadManagementKeys = authorization.can(managementKeyAccess.workspace.read);
  const canReadKeys = authorization.can(inferenceKeyAccess.read);
  const canCreateKeys = authorization.can(inferenceKeyAccess.create);
  const canRevokeKeys = authorization.can(inferenceKeyAccess.revoke);
  const canReadMembers = authorization.can(workspaceMemberAccess.read);
  const canListCandidates = authorization.can(workspaceMemberAccess.listCandidates);
  const canManageMembers = authorization.can(workspaceMemberAccess.add);
  const canRemoveMembers = authorization.can(workspaceMemberAccess.remove);
  const canUpdate = authorization.can(workspaceAccess.update);
  const canDelete = authorization.can(workspaceAccess.delete);
  const keysQuery = useInferenceKeys(orgId, workspaceRef, { enabled: canReadKeys });

  const [keyOpen, setKeyOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  const revokeKey = useRevokeInferenceKeyMutation(orgId, workspaceRef);
  const rename = useRenameWorkspaceMutation(orgId, workspaceRef);
  const remove = useDeleteWorkspaceMutation(orgId);
  const defaultTab = canReadKeys ? 'keys' : canReadManagementKeys ? 'management-keys' : 'members';

  if (authorization.isLoading) return <LoadingState label="Loading workspace permissions..." />;
  if (authorization.isError)
    return <ErrorState error={authorization.error} resource="workspace permissions" onRetry={() => authorization.refetch()} />;
  if (!canReadWorkspace) return <ErrorState message="You do not have access to this workspace." />;
  if (workspaceQuery.isLoading) return <LoadingState label="Loading workspace..." />;
  if (workspaceQuery.isError) return <ErrorState error={workspaceQuery.error} resource="workspace" onRetry={() => workspaceQuery.refetch()} />;
  if (!workspace) return <ErrorState message="Workspace not found" />;

  return (
    <PageShell>
      <div className="flex items-center gap-4 text-sm text-muted-foreground mb-4">
        <Link href={backHref} className="hover:text-foreground flex items-center gap-1">
          <ArrowLeft className="w-4 h-4" /> Back to {backLabel}
        </Link>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
            <TerminalSquare className="w-6 h-6 text-primary" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-3xl font-bold tracking-tight">{workspace.name}</h1>
              <Badge variant="mono">{workspace.slug}</Badge>
            </div>
          </div>
        </div>
        <div className="flex gap-2">
          {canUpdate && (
            <Button variant="outline" onClick={() => setRenameOpen(true)}>
              <Pencil className="w-4 h-4" /> Rename
            </Button>
          )}
          {canDelete && (
            <ConfirmButton
              variant="outline"
              size="default"
              className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
              title="Delete Workspace"
              description={`Deleting ${workspace.name} also deletes its inference keys and memberships. Usage already recorded remains on the organization’s bill.`}
              confirmLabel="Delete Workspace"
              pending={remove.isPending}
              onConfirm={async () => {
                await remove.mutateAsync({ orgId, workspaceRef });
                setLocation(backHref);
              }}
            >
              <Trash2 className="w-4 h-4" /> Delete
            </ConfirmButton>
          )}
        </div>
      </div>

      <Tabs defaultValue={defaultTab} className="w-full">
        <TabsList className="mb-4">
          {canReadKeys && (
            <TabsTrigger value="keys" className="gap-2">
              <Key className="w-4 h-4" /> Inference Keys
            </TabsTrigger>
          )}
          {canReadManagementKeys && <TabsTrigger value="management-keys">Management Keys</TabsTrigger>}
          {canReadMembers && (
            <TabsTrigger value="members" className="gap-2">
              <Users className="w-4 h-4" /> Members
            </TabsTrigger>
          )}
        </TabsList>
        {canReadManagementKeys && (
          <TabsContent value="management-keys">
            <WorkspaceManagementKeys orgId={orgId} workspaceId={workspace.id} />
          </TabsContent>
        )}

        {canReadKeys && (
          <TabsContent value="keys" className="space-y-4 mt-0">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-semibold">Inference Keys</h2>
              {canCreateKeys && (
                <Button onClick={() => setKeyOpen(true)} size="sm">
                  <Plus className="w-4 h-4" /> Generate Key
                </Button>
              )}
            </div>
            <KeysTable
              resource="inference keys"
              keys={keysQuery.data}
              isLoading={keysQuery.isLoading}
              isError={keysQuery.isError}
              error={keysQuery.error}
              onRetry={() => keysQuery.refetch()}
              emptyText="No inference keys generated."
              revokeDescription="Requests using this inference key will stop working immediately. This cannot be undone."
              onRevoke={canRevokeKeys ? (key) => revokeKey.mutateAsync({ orgId, workspaceRef, keyId: key.id }) : undefined}
              revokePending={canRevokeKeys ? revokeKey.isPending : undefined}
            />
          </TabsContent>
        )}

        {canReadMembers && (
          <TabsContent value="members" className="space-y-4 mt-0">
            <WorkspaceMembersPanel
              orgId={orgId}
              workspaceRef={workspaceRef}
              heading="Workspace Members"
              canListCandidates={canListCandidates}
              canManageMembers={canManageMembers}
              canRemoveMembers={canRemoveMembers}
            />
          </TabsContent>
        )}
      </Tabs>

      {canCreateKeys && user && (
        <InferenceKeyDialog
          orgId={orgId}
          workspaceRef={workspaceRef}
          open={keyOpen}
          onOpenChange={setKeyOpen}
          onCreated={setToken}
          currentUser={user}
        />
      )}

      {canUpdate && (
        <FormDialog
          open={renameOpen}
          onOpenChange={setRenameOpen}
          title="Rename Workspace"
          schema={nameSchema}
          defaultValues={{ name: workspace.name }}
          onSubmit={(values) => rename.mutateAsync({ orgId, workspaceRef, data: values })}
          submitLabel="Save"
          pending={rename.isPending}
        >
          {(form) => (
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}
        </FormDialog>
      )}

      <KeyRevealDialog open={!!token} onOpenChange={(v) => !v && setToken(null)} token={token} />
    </PageShell>
  );
}
