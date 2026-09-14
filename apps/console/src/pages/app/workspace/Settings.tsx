import { WorkspaceManagementKeys } from '@/components/shared/workspace-management-keys';
import { managementKeyAccess } from '@/features/keys/policy';
import { SettingsLayout } from '@/components/shared/settings-layout';
import { useState } from 'react';
import { useLocation } from 'wouter';
import { useRequiredOrgId } from '@/lib/session';
import { useWorkspace, useRenameWorkspaceMutation, useDeleteWorkspaceMutation } from '@/features/workspaces/hooks';
import { Card, Button, ConfirmButton, Input, Label, TabsContent } from '@/components/ui/elements';
import { Trash2, UserPlus, Users } from 'lucide-react';
import { LoadingState, ErrorState } from '@/components/shared/states';
import { WorkspaceMembersPanel } from '@/components/shared/workspace-members-panel';
import { useRequiredParam } from '@/lib/route';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { useCreateInvitationMutation } from '@/features/invitations/hooks';
import { InvitationDialog, invitationRequest } from '@/components/shared/invitation-dialog';
import { OneTimeValueDialog } from '@/components/shared/one-time-value-dialog';
import { useAuthorization } from '@/features/permissions/hooks';
import { orgMemberAccess, workspaceMemberAccess } from '@/features/members/policy';
import { workspaceAccess } from '@/features/workspaces/policy';

export default function WorkspaceSettings() {
  const workspaceRef = useRequiredParam('workspaceRef');
  return <WorkspaceSettingsContent key={workspaceRef} workspaceRef={workspaceRef} />;
}

function WorkspaceSettingsContent({ workspaceRef }: { workspaceRef: string }) {
  const orgId = useRequiredOrgId();
  const [, setLocation] = useLocation();

  const workspaceQuery = useWorkspace(orgId, workspaceRef);
  const workspace = workspaceQuery.data;
  const workspaceAuthorization = useAuthorization('workspace');
  const orgAuthorization = useAuthorization('org');
  const canReadMembers = workspaceAuthorization.can(workspaceMemberAccess.read);
  const canListCandidates = workspaceAuthorization.can(workspaceMemberAccess.listCandidates);
  const canManageMembers = workspaceAuthorization.can(workspaceMemberAccess.add);
  const canRemoveMembers = workspaceAuthorization.can(workspaceMemberAccess.remove);
  const canUpdate = workspaceAuthorization.can(workspaceAccess.update);
  const canReadManagementKeys = workspaceAuthorization.can(managementKeyAccess.workspace.read);
  const canDelete = workspaceAuthorization.can(workspaceAccess.delete);

  const [name, setName] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [invitationUrl, setInvitationUrl] = useState<string | null>(null);

  const rename = useRenameWorkspaceMutation(orgId, workspaceRef);
  const remove = useDeleteWorkspaceMutation(orgId);
  const createInvitation = useCreateInvitationMutation(orgId);
  const canInvite = orgAuthorization.can(orgMemberAccess.invite);

  if (workspaceQuery.isLoading) return <LoadingState label="Loading workspace..." />;
  if (workspaceQuery.isError) return <ErrorState error={workspaceQuery.error} resource="workspace" onRetry={() => workspaceQuery.refetch()} />;
  if (!workspace) return <ErrorState message="Workspace not found" />;

  const draft = name ?? workspace.name;

  return (
    <PageShell className="max-w-none space-y-0 p-0 sm:p-0">
      <SettingsLayout
        header={<PageHeader title="Workspace Settings" description={<span className="font-mono">{workspace.slug}</span>} />}
        categories={[
          ...(canUpdate ? [{ id: 'general', label: 'General' }] : []),
          ...(canReadManagementKeys ? [{ id: 'management-keys', label: 'Management Keys' }] : []),
          ...(canReadMembers ? [{ id: 'members', label: 'Members' }] : []),
          ...(canDelete ? [{ id: 'danger', label: 'Danger zone' }] : []),
        ]}
      >
        {canUpdate && (
          <TabsContent value="general" className="mt-0">
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
          </TabsContent>
        )}

        {canReadManagementKeys && (
          <TabsContent value="management-keys" className="mt-0">
            <WorkspaceManagementKeys orgId={orgId} workspaceId={workspace.id} />
          </TabsContent>
        )}
        {canReadMembers && (
          <TabsContent value="members" className="mt-0 space-y-3">
            <WorkspaceMembersPanel
              orgId={orgId}
              workspaceRef={workspaceRef}
              heading={
                <span className="flex items-center gap-2">
                  <Users className="w-5 h-5 text-muted-foreground" /> Members
                </span>
              }
              actions={
                canInvite ? (
                  <Button size="sm" variant="outline" onClick={() => setInviteOpen(true)}>
                    <UserPlus className="w-4 h-4" /> Invite by email
                  </Button>
                ) : undefined
              }
              canListCandidates={canListCandidates}
              canManageMembers={canManageMembers}
              canRemoveMembers={canRemoveMembers}
            />
          </TabsContent>
        )}

        {canDelete && (
          <TabsContent value="danger" className="mt-0">
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
                <Trash2 className="w-4 h-4" /> Delete Workspace
              </ConfirmButton>
            </Card>
          </TabsContent>
        )}
      </SettingsLayout>

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
