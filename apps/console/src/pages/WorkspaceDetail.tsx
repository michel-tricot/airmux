import { useState } from 'react';
import { useGetWorkspace, useListInferenceKeys, useListWorkspaceMembers, useCreateInferenceKey, useAddWorkspaceMember, useRemoveWorkspaceMember, useRevokeInferenceKey, useDeleteWorkspace, getListInferenceKeysQueryKey, getListWorkspaceMembersQueryKey, getListWorkspacesQueryKey, getGetWorkspaceQueryKey, getListUserWorkspacesQueryKey } from '@workspace/api-client-react';
import { Card, Button, Input, Label, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Modal, Badge, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/elements';
import { TerminalSquare, Plus, ArrowLeft, Key, Users, Trash2, X } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link, useParams, useLocation } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';

export default function WorkspaceDetail() {
  const { id } = useParams();
  const workspaceId = Number(id);
  const [, setLocation] = useLocation();
  const queryClient = useQueryClient();

  const { data: ws, isLoading: loadingWs } = useGetWorkspace(workspaceId, { query: { enabled: !!workspaceId, queryKey: getGetWorkspaceQueryKey(workspaceId) } });
  const { data: keys } = useListInferenceKeys(workspaceId, { query: { enabled: !!workspaceId, queryKey: getListInferenceKeysQueryKey(workspaceId) } });
  const { data: members } = useListWorkspaceMembers(workspaceId, { query: { enabled: !!workspaceId, queryKey: getListWorkspaceMembersQueryKey(workspaceId) } });

  const [keyOpen, setKeyOpen] = useState(false);
  const [memberOpen, setMemberOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const [keyForm, setKeyForm] = useState({ name: '' });
  const [memberForm, setMemberForm] = useState({ userId: '' });
  const [createdKey, setCreatedKey] = useState<any>(null);

  const createKey = useCreateInferenceKey({ mutation: { onSuccess: (data) => { queryClient.invalidateQueries({ queryKey: getListInferenceKeysQueryKey(workspaceId) }); setKeyOpen(false); setCreatedKey(data); } } });
  const addMember = useAddWorkspaceMember({ mutation: { onSuccess: (data, variables) => { queryClient.invalidateQueries({ queryKey: getListWorkspaceMembersQueryKey(workspaceId) }); queryClient.invalidateQueries({ queryKey: getListUserWorkspacesQueryKey(variables.data.userId) }); setMemberOpen(false); } } });
  const removeMember = useRemoveWorkspaceMember({ mutation: { onSuccess: (data, variables) => { queryClient.invalidateQueries({ queryKey: getListWorkspaceMembersQueryKey(workspaceId) }); queryClient.invalidateQueries({ queryKey: getListUserWorkspacesQueryKey(variables.userId) }); } } });
  const revokeKey = useRevokeInferenceKey({ mutation: { onSuccess: () => queryClient.invalidateQueries({ queryKey: getListInferenceKeysQueryKey(workspaceId) }) } });
  const deleteWs = useDeleteWorkspace({ mutation: { onSuccess: () => { queryClient.invalidateQueries({ queryKey: getListWorkspacesQueryKey(ws!.orgId) }); setLocation(`/organizations/${ws!.orgId}`); } } });

  if (loadingWs) return <div className="p-8 text-center">Loading...</div>;
  if (!ws) return <div className="p-8 text-center text-destructive">Workspace not found</div>;

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex items-center gap-4 text-sm text-muted-foreground mb-4">
        <Link href={`/organizations/${ws.orgId}`} className="hover:text-foreground flex items-center gap-1"><ArrowLeft className="w-4 h-4" /> Back to {ws.orgName}</Link>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
            <TerminalSquare className="w-6 h-6 text-primary" />
          </div>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{ws.name}</h1>
            <p className="text-muted-foreground font-mono text-sm">{ws.slug}</p>
          </div>
        </div>
        <Button variant="outline" className="text-destructive hover:bg-destructive hover:text-destructive-foreground" onClick={() => setDeleteOpen(true)}>
          <Trash2 className="w-4 h-4 mr-2" /> Delete Workspace
        </Button>
      </div>

      <Tabs defaultValue="keys" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="keys" className="gap-2"><Key className="w-4 h-4"/> Inference Keys</TabsTrigger>
          <TabsTrigger value="members" className="gap-2"><Users className="w-4 h-4"/> Members</TabsTrigger>
        </TabsList>

        <TabsContent value="keys" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Inference Keys</h2>
            <Button onClick={() => setKeyOpen(true)} size="sm"><Plus className="w-4 h-4 mr-1"/> Generate Key</Button>
          </div>
          <Card>
            {keys && keys.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Prefix</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Last Used</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {keys.map(key => (
                    <TableRow key={key.id}>
                      <TableCell className="font-medium">{key.name}</TableCell>
                      <TableCell className="font-mono text-xs">{key.prefix}***</TableCell>
                      <TableCell><Badge variant={key.status === 'active' ? 'success' : 'outline'}>{key.status.toUpperCase()}</Badge></TableCell>
                      <TableCell className="text-muted-foreground text-sm">{key.lastUsedAt ? formatDate(key.lastUsedAt) : 'Never'}</TableCell>
                      <TableCell className="text-muted-foreground text-sm">{formatDate(key.createdAt)}</TableCell>
                      <TableCell className="text-right">
                        {key.status === 'active' && (
                          <Button variant="ghost" size="sm" className="text-destructive hover:bg-destructive/10" onClick={() => revokeKey.mutate({ workspaceId, keyId: key.id })}>
                            Revoke
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-8 text-center text-muted-foreground">No inference keys generated.</div>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="members" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Workspace Members</h2>
            <Button onClick={() => setMemberOpen(true)} size="sm"><Plus className="w-4 h-4 mr-1"/> Add Member</Button>
          </div>
          <Card>
            {members && members.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>User</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Added</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {members.map(member => (
                    <TableRow key={member.userId}>
                      <TableCell className="font-medium">
                        <Link href={`/users/${member.userId}`} className="hover:text-primary">{member.name}</Link>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{member.email}</TableCell>
                      <TableCell className="text-muted-foreground text-sm">{formatDate(member.addedAt)}</TableCell>
                      <TableCell className="text-right">
                         <Button variant="ghost" size="icon" className="text-destructive hover:bg-destructive/10" onClick={() => removeMember.mutate({ workspaceId, userId: member.userId })}>
                           <X className="w-4 h-4" />
                         </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-8 text-center text-muted-foreground">No members found in this workspace.</div>
            )}
          </Card>
        </TabsContent>
      </Tabs>

      <Modal open={keyOpen} onOpenChange={setKeyOpen} title="Generate Inference Key" description="This key grants access to models scoped to this workspace.">
        <form onSubmit={e => { e.preventDefault(); createKey.mutate({ workspaceId, data: keyForm }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label>Key Name</Label>
            <Input required value={keyForm.name} placeholder="e.g. Chatbot Prod" onChange={e => setKeyForm(p => ({...p, name: e.target.value}))} />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setKeyOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createKey.isPending}>Generate</Button>
          </div>
        </form>
      </Modal>

      <Modal open={memberOpen} onOpenChange={setMemberOpen} title="Add Member">
        <form onSubmit={e => { e.preventDefault(); addMember.mutate({ workspaceId, data: { userId: Number(memberForm.userId) } }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label>User ID</Label>
            <Input required type="number" value={memberForm.userId} onChange={e => setMemberForm(p => ({...p, userId: e.target.value}))} />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setMemberOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={addMember.isPending}>Add</Button>
          </div>
        </form>
      </Modal>

      <Modal open={deleteOpen} onOpenChange={setDeleteOpen} title="Delete Workspace" description="This action cannot be undone. All inference keys will be revoked immediately.">
        <div className="space-y-4 pt-4">
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setDeleteOpen(false)}>Cancel</Button>
            <Button variant="destructive" onClick={() => deleteWs.mutate({ workspaceId })}>Delete Forever</Button>
          </div>
        </div>
      </Modal>

      {createdKey && (
        <KeyRevealDialog open={!!createdKey} onOpenChange={(v) => !v && setCreatedKey(null)} createdKey={createdKey} />
      )}
    </div>
  );
}
