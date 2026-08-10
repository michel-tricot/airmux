import { useState } from 'react';
import { useParams, useLocation } from 'wouter';
import { useSession } from '@/lib/session';
import { useWorkspace, useRenameWorkspaceMutation, useDeleteWorkspaceMutation } from '@/features/workspaces/hooks';
import {
  useOrgMembers,
  useWorkspaceMembers,
  useAddWorkspaceMemberMutation,
  useRemoveWorkspaceMemberMutation,
} from '@/features/members/hooks';
import { Card, Button, Input, Label } from '@/components/ui/elements';
import { Trash2, Users } from 'lucide-react';
import { LoadingState, ErrorState } from '@/components/shared/states';
import { MembersPanel } from '@/components/shared/members-panel';

export default function WorkspaceSettings() {
  const { workspaceRef } = useParams();
  const { orgId } = useSession();
  const [, setLocation] = useLocation();

  const { data: workspace, isLoading } = useWorkspace(orgId!, workspaceRef!);

  const [name, setName] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const membersQuery = useWorkspaceMembers(orgId!, workspaceRef!);
  const { data: orgUsers } = useOrgMembers(orgId!);
  const members = membersQuery.data;
  const candidates = orgUsers?.filter(u => !members?.some(m => m.user_id === u.user_id));
  const describe = (userId: string) => orgUsers?.find(u => u.user_id === userId);

  const addMember = useAddWorkspaceMemberMutation(orgId!, workspaceRef!);
  const removeMember = useRemoveWorkspaceMemberMutation(orgId!, workspaceRef!);
  const rename = useRenameWorkspaceMutation(orgId!, workspaceRef!);
  const remove = useDeleteWorkspaceMutation(orgId!);

  if (isLoading) return <LoadingState label="Loading workspace..." />;
  if (!workspace) return <ErrorState message="Workspace not found" />;

  const draft = name ?? workspace.name;

  return (
    <div className="flex-1 p-8 max-w-4xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Workspace Settings</h1>
        <p className="text-muted-foreground mt-1 text-sm font-mono">{workspace.slug}</p>
      </div>

      <Card className="p-6 space-y-4">
        <h2 className="text-lg font-semibold">General</h2>
        <form
          onSubmit={e => {
            e.preventDefault();
            rename.mutate({ workspaceRef: workspaceRef!, data: { name: draft } }, { onSuccess: () => setName(null) });
          }}
          className="flex items-end gap-3 max-w-md"
        >
          <div className="flex-1 space-y-2">
            <Label htmlFor="ws-name">Workspace name</Label>
            <Input id="ws-name" required value={draft} onChange={e => setName(e.target.value)} />
          </div>
          <Button type="submit" disabled={rename.isPending || draft === workspace.name}>Save</Button>
        </form>
        <div className="space-y-2 max-w-md">
          <Label htmlFor="ws-slug">Slug</Label>
          <Input id="ws-slug" readOnly disabled value={workspace.slug} className="font-mono" />
          <p className="text-xs text-muted-foreground">
             The workspace slug is used in links and command-line tools and cannot be changed.
          </p>
        </div>
      </Card>

      <div className="space-y-3">
        <MembersPanel
          heading={
            <span className="flex items-center gap-2">
              <Users className="w-5 h-5 text-muted-foreground" /> Members
            </span>
          }
          members={members}
          isLoading={membersQuery.isLoading}
          isError={membersQuery.isError}
          onRetry={() => membersQuery.refetch()}
          emptyText="No members in this workspace."
          renderName={member => describe(member.user_id)?.name ?? 'Member'}
          renderEmail={member => describe(member.user_id)?.email ?? member.user_id}
          add={{
            candidates: (candidates ?? []).map(user => ({ value: user.user_id, label: `${user.name} (${user.email})` })),
            dialogTitle: 'Add Member',
            dialogDescription: 'Choose someone who already belongs to this organization.',
            placeholder: 'Select an org member',
            onAdd: userId => addMember.mutateAsync({ workspaceRef: workspaceRef!, userId }),
            pending: addMember.isPending,
          }}
          remove={{
            title: member => `Remove ${describe(member.user_id)?.name ?? 'this member'} from the workspace?`,
            description: 'They lose access to this workspace but stay in the organization.',
            onRemove: member => removeMember.mutate({ workspaceRef: workspaceRef!, userId: member.user_id }),
            pending: removeMember.isPending,
          }}
        />
      </div>

      <Card className="p-6 space-y-4 border-destructive/30">
        <h2 className="text-lg font-semibold text-destructive">Danger zone</h2>
        <p className="text-sm text-muted-foreground">
            Deleting <strong>{workspace.name}</strong> cannot be undone. Usage already recorded remains on the organization’s bill.
        </p>
        {confirming ? (
          <div className="flex items-center gap-2">
            <Button variant="destructive" disabled={remove.isPending}
              onClick={() => remove.mutate({ workspaceRef: workspaceRef! }, { onSuccess: () => setLocation('/org') })}>
              Confirm delete
            </Button>
            <Button variant="outline" onClick={() => setConfirming(false)}>Cancel</Button>
          </div>
        ) : (
          <Button variant="outline" className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
            onClick={() => setConfirming(true)}>
            <Trash2 className="w-4 h-4 mr-2" /> Delete Workspace
          </Button>
        )}
      </Card>
    </div>
  );
}
