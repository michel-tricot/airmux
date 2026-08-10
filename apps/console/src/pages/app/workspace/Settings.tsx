import { useState } from 'react';
import { useParams, useLocation } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';
import { useSession } from '@/lib/session';
import { orgScope } from '@/lib/api';
import {
  useGetWorkspace,
  useUpdateWorkspace,
  useDeleteWorkspace,
  useListMembers,
  useAddMember,
  useRemoveMember,
  useListOrgUsers,
  getGetWorkspaceQueryKey,
  getListWorkspacesQueryKey,
  getListMembersQueryKey,
  getListOrgUsersQueryKey,
} from '@workspace/api-client-react';
import { Card, Button, Input, Label, Dropdown, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Modal, ConfirmButton } from '@/components/ui/elements';
import { Trash2, Plus, Users, UserMinus } from 'lucide-react';

export default function WorkspaceSettings() {
  const { workspaceRef } = useParams();
  const { orgId } = useSession();
  const queryClient = useQueryClient();
  const [, setLocation] = useLocation();
  const scope = orgScope(orgId!);

  const workspacesKey = [...getListWorkspacesQueryKey(), orgId];
  const { data: workspace, isLoading } = useGetWorkspace(workspaceRef!, {
    query: { queryKey: [...getGetWorkspaceQueryKey(workspaceRef!), orgId], retry: false },
    request: scope,
  });

  const [name, setName] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [memberOpen, setMemberOpen] = useState(false);
  const [memberId, setMemberId] = useState('');

  const membersKey = [...getListMembersQueryKey(workspaceRef!), orgId];
  const orgUsersKey = [...getListOrgUsersQueryKey(), orgId];
  const { data: members } = useListMembers(workspaceRef!, { query: { queryKey: membersKey }, request: scope });
  const { data: orgUsers } = useListOrgUsers({ query: { queryKey: orgUsersKey }, request: scope });
  const candidates = orgUsers?.filter(u => !members?.some(m => m.user_id === u.user_id));

  const invalidateMembers = () => queryClient.invalidateQueries({ queryKey: membersKey });
  const addMember = useAddMember({
    mutation: { onSuccess: () => { invalidateMembers(); setMemberOpen(false); setMemberId(''); } },
    request: scope,
  });
  const removeMember = useRemoveMember({ mutation: { onSuccess: invalidateMembers }, request: scope });

  const rename = useUpdateWorkspace({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: workspacesKey });
        queryClient.invalidateQueries({ queryKey: [...getGetWorkspaceQueryKey(workspaceRef!), orgId] });
        setName(null);
      },
    },
    request: scope,
  });
  const remove = useDeleteWorkspace({
    mutation: {
      onSuccess: () => { queryClient.invalidateQueries({ queryKey: workspacesKey }); setLocation('/org'); },
      onError: () => setDeleteError('We couldn’t delete this workspace. Please try again.'),
    },
    request: scope,
  });

  if (isLoading) return <div className="p-8 text-center text-muted-foreground font-mono text-sm">Loading workspace...</div>;
  if (!workspace) return <div className="p-8 text-center text-destructive">Workspace not found</div>;

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
          onSubmit={e => { e.preventDefault(); rename.mutate({ workspaceRef: workspaceRef!, data: { name: draft } }); }}
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
        <div className="flex justify-between items-center">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Users className="w-5 h-5 text-muted-foreground" /> Members
          </h2>
          <Button onClick={() => setMemberOpen(true)} size="sm"><Plus className="w-4 h-4 mr-1" /> Add Member</Button>
        </div>
        <Card>
          {members && members.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map(member => {
                  const described = orgUsers?.find(u => u.user_id === member.user_id);
                  return (
                    <TableRow key={member.user_id}>
                      <TableCell className="font-medium">{described?.name ?? 'Member'}</TableCell>
                      <TableCell className="text-muted-foreground">{described?.email ?? member.user_id}</TableCell>
                      <TableCell className="text-right">
                        <ConfirmButton
                          title={`Remove ${described?.name ?? 'this member'} from the workspace?`}
                          description="They lose access to this workspace but stay in the organization."
                          confirmLabel="Remove member"
                          pending={removeMember.isPending}
                          aria-label="Remove member"
                          onConfirm={() => removeMember.mutate({ workspaceRef: workspaceRef!, userId: member.user_id })}>
                          <UserMinus className="w-4 h-4" />
                        </ConfirmButton>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          ) : (
            <div className="p-8 text-center text-muted-foreground">No members in this workspace.</div>
          )}
        </Card>
      </div>

      <Card className="p-6 space-y-4 border-destructive/30">
        <h2 className="text-lg font-semibold text-destructive">Danger zone</h2>
        <p className="text-sm text-muted-foreground">
            Deleting <strong>{workspace.name}</strong> cannot be undone. Usage already recorded remains on the organization’s bill.
        </p>
        {deleteError && <p className="text-sm text-destructive">{deleteError}</p>}
        {confirming ? (
          <div className="flex items-center gap-2">
            <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate({ workspaceRef: workspaceRef! })}>
              Confirm delete
            </Button>
            <Button variant="outline" onClick={() => setConfirming(false)}>Cancel</Button>
          </div>
        ) : (
          <Button variant="outline" className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
            onClick={() => { setDeleteError(null); setConfirming(true); }}>
            <Trash2 className="w-4 h-4 mr-2" /> Delete Workspace
          </Button>
        )}
      </Card>

      <Modal open={memberOpen} onOpenChange={setMemberOpen} title="Add Member" description="Choose someone who already belongs to this organization.">
        <form onSubmit={e => { e.preventDefault(); addMember.mutate({ workspaceRef: workspaceRef!, userId: memberId }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label htmlFor="workspace-member">User</Label>
            <Dropdown
              aria-label="User"
              value={memberId}
              onValueChange={setMemberId}
              placeholder="Select an org member"
              options={(candidates ?? []).map(user => ({ value: user.user_id, label: `${user.name} (${user.email})` }))}
            />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setMemberOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={!memberId || addMember.isPending}>Add</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
