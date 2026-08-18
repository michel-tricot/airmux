import { useState } from 'react';
import { useLocation } from 'wouter';
import { useRequiredOrgId } from '@/lib/session';
import { useWorkspace, useRenameWorkspaceMutation, useDeleteWorkspaceMutation } from '@/features/workspaces/hooks';
import {
  useWorkspaceMembers,
  useWorkspaceMemberCandidates,
  useAddWorkspaceMemberMutation,
  useRemoveWorkspaceMemberMutation,
  workspaceRoleOptions,
} from '@/features/members/hooks';
import type { WorkspaceRole } from '@workspace/api-client-react';
import { Card, Button, ConfirmButton, Input, Label } from '@/components/ui/elements';
import { Trash2, UserPlus, Users } from 'lucide-react';
import { LoadingState, ErrorState } from '@/components/shared/states';
import { MembersPanel } from '@/components/shared/members-panel';
import { useRequiredParam } from '@/lib/route';
import { PageShell } from '@/components/shared/page-shell';
import { useCreateInvitationMutation } from '@/features/invitations/hooks';
import { InvitationDialog, invitationRequest } from '@/components/shared/invitation-dialog';
import { OneTimeValueDialog } from '@/components/shared/one-time-value-dialog';
import { hasPermission, useEffectivePermissions } from '@/features/permissions/hooks';

export default function WorkspaceSettings() {
  const workspaceRef = useRequiredParam('workspaceRef');
  return <WorkspaceSettingsContent key={workspaceRef} workspaceRef={workspaceRef} />;
}

function WorkspaceSettingsContent({ workspaceRef }: { workspaceRef: string }) {
  const orgId = useRequiredOrgId();
  const [, setLocation] = useLocation();

  const workspaceQuery = useWorkspace(orgId, workspaceRef);
  const workspace = workspaceQuery.data;
  const workspacePermissionsQuery = useEffectivePermissions({ orgId, workspaceRef });
  const orgPermissionsQuery = useEffectivePermissions({ orgId });
  const workspacePermissions = workspacePermissionsQuery.data?.permissions;
  const orgPermissions = orgPermissionsQuery.data?.permissions;
  const canReadMembers = hasPermission(workspacePermissions, 'members.read');
  const canManageMembers = hasPermission(workspacePermissions, 'members.manage');
  const canUpdate = hasPermission(workspacePermissions, 'workspaces.update');
  const canDelete = hasPermission(workspacePermissions, 'workspaces.delete');

  const [name, setName] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [invitationUrl, setInvitationUrl] = useState<string | null>(null);

  const membersQuery = useWorkspaceMembers(orgId, workspaceRef, canReadMembers);
  const candidatesQuery = useWorkspaceMemberCandidates(orgId, workspaceRef, canManageMembers);
  const members = membersQuery.data;
  const candidates = candidatesQuery.data;

  const addMember = useAddWorkspaceMemberMutation(orgId, workspaceRef);
  const removeMember = useRemoveWorkspaceMemberMutation(orgId, workspaceRef);
  const rename = useRenameWorkspaceMutation(orgId, workspaceRef);
  const remove = useDeleteWorkspaceMutation(orgId);
  const createInvitation = useCreateInvitationMutation(orgId);
  const canInvite = hasPermission(orgPermissions, 'members.manage');

  if (workspaceQuery.isLoading) return <LoadingState label="Loading workspace..." />;
  if (workspaceQuery.isError) return <ErrorState error={workspaceQuery.error} resource="workspace" onRetry={() => workspaceQuery.refetch()} />;
  if (workspacePermissionsQuery.isLoading) return <LoadingState label="Loading workspace permissions..." />;
  if (workspacePermissionsQuery.isError) {
    return (
      <ErrorState error={workspacePermissionsQuery.error} resource="workspace permissions" onRetry={() => workspacePermissionsQuery.refetch()} />
    );
  }
  if (!workspace) return <ErrorState message="Workspace not found" />;

  const draft = name ?? workspace.name;

  return (
    <PageShell className="max-w-4xl">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Workspace Settings</h1>
        <p className="text-muted-foreground mt-1 text-sm font-mono">{workspace.slug}</p>
      </div>

      {canUpdate && (
        <Card className="p-6 space-y-4">
          <h2 className="text-lg font-semibold">General</h2>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              rename.mutate({ orgId, workspaceRef, data: { name: draft } }, { onSuccess: () => setName(null) });
            }}
            className="flex items-end gap-3 max-w-md"
          >
            <div className="flex-1 space-y-2">
              <Label htmlFor="ws-name">Workspace name</Label>
              <Input id="ws-name" required value={draft} onChange={(e) => setName(e.target.value)} />
            </div>
            <Button type="submit" disabled={rename.isPending || draft === workspace.name}>
              Save
            </Button>
          </form>
          <div className="space-y-2 max-w-md">
            <Label htmlFor="ws-slug">Slug</Label>
            <Input id="ws-slug" readOnly value={workspace.slug} className="font-mono" />
            <p className="text-xs text-muted-foreground">The workspace slug is used in links and command-line tools and cannot be changed.</p>
          </div>
        </Card>
      )}

      {canReadMembers && (
        <div className="space-y-3">
          <MembersPanel
            heading={
              <span className="flex items-center gap-2">
                <Users className="w-5 h-5 text-muted-foreground" /> Members
              </span>
            }
            members={members}
            isLoading={membersQuery.isLoading}
            isError={membersQuery.isError || candidatesQuery.isError}
            error={membersQuery.error ?? candidatesQuery.error}
            onRetry={() => Promise.all([membersQuery.refetch(), ...(canManageMembers ? [candidatesQuery.refetch()] : [])])}
            emptyText="No members in this workspace."
            actions={
              canInvite ? (
                <Button size="sm" variant="outline" onClick={() => setInviteOpen(true)}>
                  <UserPlus className="w-4 h-4 mr-1" /> Invite by email
                </Button>
              ) : undefined
            }
            add={
              canManageMembers
                ? {
                    candidates: candidates?.map((user) => ({ value: user.user_id, label: `${user.name} (${user.email})` })) ?? [],
                    dialogTitle: 'Add Member',
                    dialogDescription: 'Choose someone who already belongs to this organization.',
                    placeholder: 'Select an org member',
                    roles: workspaceRoleOptions,
                    defaultRole: 'member',
                    onAdd: (userId, role) => addMember.mutateAsync({ orgId, workspaceRef, userId, data: { role: role as WorkspaceRole } }),
                    pending: addMember.isPending || candidates === undefined,
                  }
                : undefined
            }
            remove={
              canManageMembers
                ? {
                    title: (member) => `Remove ${member.name} from the workspace?`,
                    description: 'They lose access to this workspace but stay in the organization.',
                    onRemove: (member) => removeMember.mutateAsync({ orgId, workspaceRef, userId: member.user_id }),
                    pending: removeMember.isPending,
                  }
                : undefined
            }
          />
        </div>
      )}

      {canDelete && (
        <Card className="p-6 space-y-4 border-destructive/30">
          <h2 className="text-lg font-semibold text-destructive">Danger zone</h2>
          <p className="text-sm text-muted-foreground">
            Deleting <strong>{workspace.name}</strong> cannot be undone. Usage already recorded remains on the organization’s bill.
          </p>
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
              setLocation('/org');
            }}
          >
            <Trash2 className="w-4 h-4 mr-2" /> Delete Workspace
          </ConfirmButton>
        </Card>
      )}

      <InvitationDialog
        open={inviteOpen}
        onOpenChange={setInviteOpen}
        workspaces={[workspace]}
        initialWorkspaceId={workspace.id}
        pending={createInvitation.isPending}
        onSubmit={async (values) => {
          const minted = await createInvitation.mutateAsync({ orgId, data: invitationRequest(values) });
          setInvitationUrl(minted.url);
        }}
      />

      <OneTimeValueDialog
        open={invitationUrl !== null}
        onOpenChange={(open) => !open && setInvitationUrl(null)}
        value={invitationUrl}
        title="Invitation link created"
        warning="Share this link through a trusted channel. It will not be shown again."
        label="Invitation link"
        copyLabel="Copy link"
      />
    </PageShell>
  );
}
