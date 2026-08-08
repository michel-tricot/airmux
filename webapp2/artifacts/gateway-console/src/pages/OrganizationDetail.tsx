import { useState } from 'react';
import { useGetOrganization, useListWorkspaces, useListManagementKeys, useListOrgMembers, useCreateWorkspace, useCreateManagementKey, useAddOrgMember, useUpdateOrgMember, useRemoveOrgMember, useDeleteOrganization, useRevokeManagementKey, getListWorkspacesQueryKey, getListManagementKeysQueryKey, getListOrgMembersQueryKey, getListOrganizationsQueryKey, getGetOrganizationQueryKey, getListUserOrganizationsQueryKey } from '@workspace/api-client-react';
import { Card, Button, Input, Label, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Modal, Badge, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/elements';
import { Building2, Plus, ArrowLeft, Key, TerminalSquare, Users, Trash2, ShieldAlert } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link, useParams, useLocation } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';

export default function OrganizationDetail() {
  const { id } = useParams();
  const orgId = Number(id);
  const [, setLocation] = useLocation();
  const queryClient = useQueryClient();

  const { data: org, isLoading: loadingOrg } = useGetOrganization(orgId, { query: { enabled: !!orgId, queryKey: getGetOrganizationQueryKey(orgId) } });
  const { data: workspaces } = useListWorkspaces(orgId, { query: { enabled: !!orgId, queryKey: getListWorkspacesQueryKey(orgId) } });
  const { data: mKeys } = useListManagementKeys(orgId, { query: { enabled: !!orgId, queryKey: getListManagementKeysQueryKey(orgId) } });
  const { data: members } = useListOrgMembers(orgId, { query: { enabled: !!orgId, queryKey: getListOrgMembersQueryKey(orgId) } });

  // Dialogs
  const [wsOpen, setWsOpen] = useState(false);
  const [mkOpen, setMkOpen] = useState(false);
  const [memberOpen, setMemberOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  // Forms
  const [wsForm, setWsForm] = useState({ name: '', slug: '', description: '' });
  const [mkForm, setMkForm] = useState({ name: '' });
  const [memberForm, setMemberForm] = useState({ userId: '', role: 'member' as any });

  // Key Reveal
  const [createdKey, setCreatedKey] = useState<any>(null);

  // Mutations
  const createWs = useCreateWorkspace({ mutation: { onSuccess: () => { queryClient.invalidateQueries({ queryKey: getListWorkspacesQueryKey(orgId) }); setWsOpen(false); } } });
  const createMk = useCreateManagementKey({ mutation: { onSuccess: (data) => { queryClient.invalidateQueries({ queryKey: getListManagementKeysQueryKey(orgId) }); setMkOpen(false); setCreatedKey(data); } } });
  const addMember = useAddOrgMember({ mutation: { onSuccess: (data, variables) => { queryClient.invalidateQueries({ queryKey: getListOrgMembersQueryKey(orgId) }); queryClient.invalidateQueries({ queryKey: getListUserOrganizationsQueryKey(variables.data.userId) }); setMemberOpen(false); } } });
  const removeMember = useRemoveOrgMember({ mutation: { onSuccess: (data, variables) => { queryClient.invalidateQueries({ queryKey: getListOrgMembersQueryKey(orgId) }); queryClient.invalidateQueries({ queryKey: getListUserOrganizationsQueryKey(variables.userId) }); } } });
  const revokeKey = useRevokeManagementKey({ mutation: { onSuccess: () => queryClient.invalidateQueries({ queryKey: getListManagementKeysQueryKey(orgId) }) } });
  const deleteOrg = useDeleteOrganization({ mutation: { onSuccess: () => { queryClient.invalidateQueries({ queryKey: getListOrganizationsQueryKey() }); setLocation('/organizations'); } } });

  if (loadingOrg) return <div className="p-8 text-center">Loading...</div>;
  if (!org) return <div className="p-8 text-center text-destructive">Organization not found</div>;

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex items-center gap-4 text-sm text-muted-foreground mb-4">
        <Link href="/organizations" className="hover:text-foreground flex items-center gap-1"><ArrowLeft className="w-4 h-4" /> Back to Organizations</Link>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
            <Building2 className="w-6 h-6 text-primary" />
          </div>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{org.name}</h1>
            <p className="text-muted-foreground font-mono text-sm">{org.slug}</p>
          </div>
        </div>
        <Button variant="outline" className="text-destructive hover:bg-destructive hover:text-destructive-foreground" onClick={() => setDeleteOpen(true)}>
          <Trash2 className="w-4 h-4 mr-2" /> Delete Organization
        </Button>
      </div>

      <Tabs defaultValue="workspaces" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="workspaces" className="gap-2"><TerminalSquare className="w-4 h-4"/> Workspaces</TabsTrigger>
          <TabsTrigger value="keys" className="gap-2"><Key className="w-4 h-4"/> Management Keys</TabsTrigger>
          <TabsTrigger value="members" className="gap-2"><Users className="w-4 h-4"/> Members</TabsTrigger>
        </TabsList>

        <TabsContent value="workspaces" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Workspaces</h2>
            <Button onClick={() => setWsOpen(true)} size="sm"><Plus className="w-4 h-4 mr-1"/> New Workspace</Button>
          </div>
          <Card>
            {workspaces && workspaces.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Slug</TableHead>
                    <TableHead className="text-right">Keys</TableHead>
                    <TableHead className="text-right">Members</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {workspaces.map(ws => (
                    <TableRow key={ws.id}>
                      <TableCell className="font-medium">
                        <Link href={`/workspaces/${ws.id}`} className="hover:text-primary transition-colors">{ws.name}</Link>
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">{ws.slug}</TableCell>
                      <TableCell className="text-right font-mono">{ws.inferenceKeyCount}</TableCell>
                      <TableCell className="text-right font-mono">{ws.memberCount}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-8 text-center text-muted-foreground">No workspaces yet.</div>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="keys" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Management Keys</h2>
            <Button onClick={() => setMkOpen(true)} size="sm"><Plus className="w-4 h-4 mr-1"/> Generate Key</Button>
          </div>
          <Card>
            {mKeys && mKeys.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Prefix</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {mKeys.map(key => (
                    <TableRow key={key.id}>
                      <TableCell className="font-medium">{key.name}</TableCell>
                      <TableCell className="font-mono text-xs">{key.prefix}***</TableCell>
                      <TableCell><Badge variant={key.status === 'active' ? 'success' : 'outline'}>{key.status.toUpperCase()}</Badge></TableCell>
                      <TableCell className="text-muted-foreground text-sm">{formatDate(key.createdAt)}</TableCell>
                      <TableCell className="text-right">
                        {key.status === 'active' && (
                          <Button variant="ghost" size="sm" className="text-destructive hover:bg-destructive/10" onClick={() => revokeKey.mutate({ orgId, keyId: key.id })}>
                            Revoke
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-8 text-center text-muted-foreground">No management keys generated.</div>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="members" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Organization Members</h2>
            <Button onClick={() => setMemberOpen(true)} size="sm"><Plus className="w-4 h-4 mr-1"/> Add Member</Button>
          </div>
          <Card>
            {members && members.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>User</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Role</TableHead>
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
                      <TableCell><Badge variant="secondary" className="uppercase text-[10px] tracking-wider">{member.role}</Badge></TableCell>
                      <TableCell className="text-right">
                         <Button variant="ghost" size="icon" className="text-destructive hover:bg-destructive/10" onClick={() => removeMember.mutate({ orgId, userId: member.userId })}>
                           <X className="w-4 h-4" />
                         </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-8 text-center text-muted-foreground">No members found.</div>
            )}
          </Card>
        </TabsContent>
      </Tabs>

      {/* Dialogs */}
      <Modal open={wsOpen} onOpenChange={setWsOpen} title="New Workspace">
        <form onSubmit={e => { e.preventDefault(); createWs.mutate({ orgId, data: wsForm }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label>Name</Label>
            <Input required value={wsForm.name} onChange={e => setWsForm(p => ({...p, name: e.target.value, slug: p.slug || e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '-')}))} />
          </div>
          <div className="space-y-2">
            <Label>Slug</Label>
            <Input required value={wsForm.slug} className="font-mono text-sm" onChange={e => setWsForm(p => ({...p, slug: e.target.value}))} />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setWsOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createWs.isPending}>Create</Button>
          </div>
        </form>
      </Modal>

      <Modal open={mkOpen} onOpenChange={setMkOpen} title="Generate Management Key" description="Keys allow programmatic access to the gateway API for this org.">
        <form onSubmit={e => { e.preventDefault(); createMk.mutate({ orgId, data: mkForm }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label>Key Name</Label>
            <Input required value={mkForm.name} placeholder="e.g. CI/CD Production" onChange={e => setMkForm(p => ({...p, name: e.target.value}))} />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setMkOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createMk.isPending}>Generate</Button>
          </div>
        </form>
      </Modal>

      <Modal open={memberOpen} onOpenChange={setMemberOpen} title="Add Member">
        <form onSubmit={e => { e.preventDefault(); addMember.mutate({ orgId, data: { userId: Number(memberForm.userId), role: memberForm.role } }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label>User ID</Label>
            <Input required type="number" value={memberForm.userId} onChange={e => setMemberForm(p => ({...p, userId: e.target.value}))} />
          </div>
          <div className="space-y-2">
            <Label>Role</Label>
            <select className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm" value={memberForm.role} onChange={e => setMemberForm(p => ({...p, role: e.target.value as any}))}>
              <option value="member">Member</option>
              <option value="admin">Admin</option>
              <option value="owner">Owner</option>
            </select>
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setMemberOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={addMember.isPending}>Add</Button>
          </div>
        </form>
      </Modal>

      <Modal open={deleteOpen} onOpenChange={setDeleteOpen} title="Delete Organization" description="This action cannot be undone. All workspaces and keys will be destroyed.">
        <div className="space-y-4 pt-4">
          <div className="p-4 bg-destructive/10 text-destructive rounded-md flex items-start gap-3 border border-destructive/20">
            <ShieldAlert className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <p className="text-sm font-medium">You are about to delete <strong>{org.name}</strong>. Type the organization slug to confirm.</p>
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setDeleteOpen(false)}>Cancel</Button>
            <Button variant="destructive" onClick={() => deleteOrg.mutate({ orgId })}>Delete Forever</Button>
          </div>
        </div>
      </Modal>

      {createdKey && (
        <KeyRevealDialog open={!!createdKey} onOpenChange={(v) => !v && setCreatedKey(null)} createdKey={createdKey} />
      )}
    </div>
  );
}
import { X } from 'lucide-react';