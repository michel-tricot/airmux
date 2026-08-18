import { useState } from 'react';
import * as z from 'zod';
import { Button, Input, Badge, ConfirmButton, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/elements';
import { TerminalSquare, Plus, ArrowLeft, Key, Users, Pencil, Trash2 } from 'lucide-react';
import { Link, useLocation } from 'wouter';
import { useWorkspace, useRenameWorkspaceMutation, useDeleteWorkspaceMutation } from '@/features/workspaces/hooks';
import { useInferenceKeys, useCreateInferenceKeyMutation, useRevokeInferenceKeyMutation } from '@/features/keys/hooks';
import {
  useWorkspaceMembers,
  useWorkspaceMemberCandidates,
  useAddWorkspaceMemberMutation,
  useRemoveWorkspaceMemberMutation,
  workspaceRoleOptions,
} from '@/features/members/hooks';
import type { WorkspaceRole } from '@workspace/api-client-react';
import { LoadingState, ErrorState } from '@/components/shared/states';
import { FormDialog } from '@/components/shared/form-dialog';
import { MembersPanel } from '@/components/shared/members-panel';
import { ApiKeysTable } from '@/components/shared/api-keys-table';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { PageShell } from '@/components/shared/page-shell';
import { useScopedAuthorization } from '@/features/permissions/hooks';
import { inferenceKeyAccess } from '@/features/keys/policy';
import { workspaceMemberAccess } from '@/features/members/policy';
import { workspaceAccess } from '@/features/workspaces/policy';

const nameSchema = z.object({ name: z.string().min(1, 'Name is required') });
const keyLabelSchema = z.object({ label: z.string().min(1, 'Label is required') });

interface WorkspacePanelProps {
  orgId: string;
  workspaceRef: string;
  backHref: string;
  backLabel: string;
}

export function WorkspacePanel({ orgId, workspaceRef, backHref, backLabel }: WorkspacePanelProps) {
  const [, setLocation] = useLocation();

  const authorization = useScopedAuthorization({ level: 'workspace', orgId, workspaceRef });
  const canReadWorkspace = authorization.can(workspaceAccess.read);
  const workspaceQuery = useWorkspace(orgId, workspaceRef, { enabled: canReadWorkspace });
  const workspace = workspaceQuery.data;
  const canReadKeys = authorization.can(inferenceKeyAccess.read);
  const canCreateKeys = authorization.can(inferenceKeyAccess.create);
  const canRevokeKeys = authorization.can(inferenceKeyAccess.revoke);
  const canReadMembers = authorization.can(workspaceMemberAccess.read);
  const canListCandidates = authorization.can(workspaceMemberAccess.listCandidates);
  const canAddMembers = authorization.can(workspaceMemberAccess.add);
  const canRemoveMembers = authorization.can(workspaceMemberAccess.remove);
  const canUpdate = authorization.can(workspaceAccess.update);
  const canDelete = authorization.can(workspaceAccess.delete);
  const keysQuery = useInferenceKeys(orgId, workspaceRef, { enabled: canReadKeys });
  const membersQuery = useWorkspaceMembers(orgId, workspaceRef, { enabled: canReadMembers });
  const candidatesQuery = useWorkspaceMemberCandidates(orgId, workspaceRef, { enabled: canListCandidates });
  const members = membersQuery.data;
  const candidates = candidatesQuery.data;

  const [keyOpen, setKeyOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  const createKey = useCreateInferenceKeyMutation(orgId, workspaceRef);
  const revokeKey = useRevokeInferenceKeyMutation(orgId, workspaceRef);
  const addMember = useAddWorkspaceMemberMutation(orgId, workspaceRef);
  const removeMember = useRemoveWorkspaceMemberMutation(orgId, workspaceRef);
  const rename = useRenameWorkspaceMutation(orgId, workspaceRef);
  const remove = useDeleteWorkspaceMutation(orgId);
  const defaultTab = canReadKeys ? 'keys' : 'members';

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
              <Pencil className="w-4 h-4 mr-2" /> Rename
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
              <Trash2 className="w-4 h-4 mr-2" /> Delete
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
          {canReadMembers && (
            <TabsTrigger value="members" className="gap-2">
              <Users className="w-4 h-4" /> Members
            </TabsTrigger>
          )}
        </TabsList>

        {canReadKeys && (
          <TabsContent value="keys" className="space-y-4 mt-0">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-semibold">Inference Keys</h2>
              {canCreateKeys && (
                <Button onClick={() => setKeyOpen(true)} size="sm">
                  <Plus className="w-4 h-4 mr-1" /> Generate Key
                </Button>
              )}
            </div>
            <ApiKeysTable
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
            <MembersPanel
              heading="Workspace Members"
              members={members}
              isLoading={membersQuery.isLoading}
              isError={membersQuery.isError || candidatesQuery.isError}
              error={membersQuery.error ?? candidatesQuery.error}
              onRetry={() => Promise.all([membersQuery.refetch(), ...(canListCandidates ? [candidatesQuery.refetch()] : [])])}
              emptyText="No members in this workspace."
              add={
                canAddMembers
                  ? {
                      candidates: candidates?.map((user) => ({ value: user.user_id, label: `${user.name} (${user.email})` })) ?? [],
                      dialogTitle: 'Add Member',
                      dialogDescription: 'Members are drawn from the org; the user must already belong to it.',
                      placeholder: 'Select an org member',
                      roles: workspaceRoleOptions,
                      defaultRole: 'member',
                      onAdd: (userId, role) => addMember.mutateAsync({ orgId, workspaceRef, userId, data: { role: role as WorkspaceRole } }),
                      pending: addMember.isPending || candidates === undefined,
                    }
                  : undefined
              }
              remove={
                canRemoveMembers
                  ? {
                      title: (member) => `Remove ${member.name} from the workspace?`,
                      description: 'They lose access to this workspace but stay in the organization.',
                      onRemove: (member) => removeMember.mutateAsync({ orgId, workspaceRef, userId: member.user_id }),
                      pending: removeMember.isPending,
                    }
                  : undefined
              }
            />
          </TabsContent>
        )}
      </Tabs>

      {canCreateKeys && (
        <FormDialog
          open={keyOpen}
          onOpenChange={setKeyOpen}
          title="Generate Inference Key"
          description="Keys let applications send requests to the models available to this workspace."
          schema={keyLabelSchema}
          defaultValues={{ label: '' }}
          onSubmit={async (values) => {
            const minted = await createKey.mutateAsync({ orgId, workspaceRef, data: values });
            setToken(minted.token);
          }}
          submitLabel="Generate"
          pending={createKey.isPending}
        >
          {(form) => (
            <FormField
              control={form.control}
              name="label"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Label</FormLabel>
                  <FormControl>
                    <Input placeholder="e.g. chatbot-prod" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          )}
        </FormDialog>
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
