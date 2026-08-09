import { useState } from 'react';
import { useParams } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';
import { useSession } from '@/lib/session';
import { orgScope } from '@/lib/api';
import {
  useGetWorkspace,
  useListMembers,
  useAddMember,
  useRemoveMember,
  useListOrgUsers,
  getGetWorkspaceQueryKey,
  getListMembersQueryKey,
  getListOrgUsersQueryKey,
} from '@workspace/api-client-react';
import { Card, Button, Label, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Modal } from '@/components/ui/elements';
import { TerminalSquare, Plus, Users, X } from 'lucide-react';

export default function WorkspaceOverview() {
  const { workspaceId } = useParams();
  const { orgId } = useSession();
  const queryClient = useQueryClient();
  const scope = orgScope(orgId!);

  const membersKey = [...getListMembersQueryKey(workspaceId!), orgId];
  const orgUsersKey = [...getListOrgUsersQueryKey(), orgId];

  const { data: workspace, isLoading } = useGetWorkspace(workspaceId!, {
    query: { queryKey: [...getGetWorkspaceQueryKey(workspaceId!), orgId], retry: false },
    request: scope,
  });
  const { data: members } = useListMembers(workspaceId!, { query: { queryKey: membersKey }, request: scope });
  const { data: orgUsers } = useListOrgUsers({ query: { queryKey: orgUsersKey }, request: scope });
  const candidates = orgUsers?.filter(u => !members?.some(m => m.user_id === u.user_id));

  const [memberOpen, setMemberOpen] = useState(false);
  const [memberId, setMemberId] = useState('');

  const invalidate = () => queryClient.invalidateQueries({ queryKey: membersKey });
  const addMember = useAddMember({
    mutation: { onSuccess: () => { invalidate(); setMemberOpen(false); setMemberId(''); } },
    request: scope,
  });
  const removeMember = useRemoveMember({ mutation: { onSuccess: invalidate }, request: scope });

  if (isLoading) return <div className="p-8 text-center text-muted-foreground font-mono text-sm">LOADING WORKSPACE...</div>;
  if (!workspace) return <div className="p-8 text-center text-destructive">Workspace not found</div>;

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
          <TerminalSquare className="w-6 h-6 text-primary" />
        </div>
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{workspace.name}</h1>
          <p className="text-muted-foreground font-mono text-sm">{workspace.id}</p>
        </div>
      </div>

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
                      <Button variant="ghost" size="icon" className="text-destructive hover:bg-destructive/10"
                        onClick={() => removeMember.mutate({ workspaceId: workspaceId!, userId: member.user_id })}>
                        <X className="w-4 h-4" />
                      </Button>
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

      <Modal open={memberOpen} onOpenChange={setMemberOpen} title="Add Member" description="Members are drawn from the org; the user must already belong to it.">
        <form onSubmit={e => { e.preventDefault(); addMember.mutate({ workspaceId: workspaceId!, userId: memberId }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label htmlFor="workspace-member">User</Label>
            <select id="workspace-member" required value={memberId} onChange={e => setMemberId(e.target.value)}
              className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm">
              <option value="" disabled>Select an org member</option>
              {candidates?.map(user => (
                <option key={user.user_id} value={user.user_id}>{user.name} ({user.email})</option>
              ))}
            </select>
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setMemberOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={addMember.isPending}>Add</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
