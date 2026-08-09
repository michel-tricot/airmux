import { useState } from 'react';
import {
  useGetOrg,
  useDeleteOrg,
  useUpdateOrg,
  useListWorkspaces,
  useCreateWorkspace,
  useListManagementKeys,
  useRevokeManagementKey,
  useListUsers,
  useListOrgUsers,
  useAddOrgUser,
  useRemoveOrgUser,
  getListOrgsQueryKey,
  getGetOrgQueryKey,
  getListWorkspacesQueryKey,
  getListManagementKeysQueryKey,
  getListOrgUsersQueryKey,
} from '@workspace/api-client-react';
import { Card, Button, Input, Label, Dropdown, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Modal, Badge, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/elements';
import { Building2, Plus, ArrowLeft, Key, TerminalSquare, Users, X, Pencil, Trash2, ShieldAlert } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link, useParams, useLocation } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';
import { orgScope } from '@/lib/api';

export default function OrganizationDetail() {
  const { orgId } = useParams();
  const [, setLocation] = useLocation();
  const queryClient = useQueryClient();
  const scope = orgScope(orgId!);

  const workspacesKey = [...getListWorkspacesQueryKey(), orgId];
  const keysKey = [...getListManagementKeysQueryKey(), orgId];
  const membersKey = [...getListOrgUsersQueryKey(), orgId];

  const { data: org, isLoading } = useGetOrg(orgId!, { query: { queryKey: [...getGetOrgQueryKey(orgId!)] } });

  const { data: workspaces } = useListWorkspaces({ query: { queryKey: workspacesKey }, request: scope });
  const { data: keys } = useListManagementKeys({ query: { queryKey: keysKey }, request: scope });
  const { data: members } = useListOrgUsers({ query: { queryKey: membersKey }, request: scope });
  const { data: users } = useListUsers();
  const outsiders = users?.filter(u => !members?.some(m => m.user_id === u.id));

  const [wsOpen, setWsOpen] = useState(false);
  const [memberOpen, setMemberOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [wsName, setWsName] = useState('');
  const [memberId, setMemberId] = useState('');
  const [name, setName] = useState('');

  const createWorkspace = useCreateWorkspace({
    mutation: { onSuccess: () => { queryClient.invalidateQueries({ queryKey: workspacesKey }); setWsOpen(false); setWsName(''); } },
    request: scope,
  });
  const revokeKey = useRevokeManagementKey({
    mutation: { onSuccess: () => queryClient.invalidateQueries({ queryKey: keysKey }) },
    request: scope,
  });
  const addMember = useAddOrgUser({
    mutation: { onSuccess: () => { queryClient.invalidateQueries({ queryKey: membersKey }); setMemberOpen(false); setMemberId(''); } },
    request: scope,
  });
  const removeMember = useRemoveOrgUser({
    mutation: { onSuccess: () => queryClient.invalidateQueries({ queryKey: membersKey }) },
    request: scope,
  });
  const rename = useUpdateOrg({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListOrgsQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetOrgQueryKey(orgId!) });
        setRenameOpen(false);
      },
    },
  });
  const deleteOrg = useDeleteOrg({
    mutation: {
      onSuccess: () => { queryClient.invalidateQueries({ queryKey: getListOrgsQueryKey() }); setLocation('/organizations'); },
      onError: (error) => setDeleteError(error.message),
    },
  });

  if (isLoading) return <div className="p-8 text-center text-muted-foreground font-mono text-sm">LOADING...</div>;
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
            <p className="text-muted-foreground font-mono text-sm">{org.id}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => { setName(org.name); setRenameOpen(true); }}>
            <Pencil className="w-4 h-4 mr-2" /> Rename
          </Button>
          <Button variant="outline" className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
            onClick={() => { setDeleteError(null); setDeleteOpen(true); }}>
            <Trash2 className="w-4 h-4 mr-2" /> Delete
          </Button>
        </div>
      </div>

      <Tabs defaultValue="workspaces" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="workspaces" className="gap-2"><TerminalSquare className="w-4 h-4" /> Workspaces</TabsTrigger>
          <TabsTrigger value="keys" className="gap-2"><Key className="w-4 h-4" /> Management Keys</TabsTrigger>
          <TabsTrigger value="members" className="gap-2"><Users className="w-4 h-4" /> Members</TabsTrigger>
        </TabsList>

        <TabsContent value="workspaces" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Workspaces</h2>
            <Button onClick={() => setWsOpen(true)} size="sm"><Plus className="w-4 h-4 mr-1" /> New Workspace</Button>
          </div>
          <Card>
            {workspaces && workspaces.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>ID</TableHead>
                    <TableHead className="text-right">Created</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {workspaces.map(ws => (
                    <TableRow key={ws.id}>
                      <TableCell className="font-medium">
                        <Link href={`/organizations/${org.id}/workspaces/${ws.id}`} className="hover:text-primary transition-colors">{ws.name}</Link>
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">{ws.id}</TableCell>
                      <TableCell className="text-right text-muted-foreground text-sm">{formatDate(ws.created_at)}</TableCell>
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
          </div>
          <Card>
            {keys && keys.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Label</TableHead>
                    <TableHead>Key</TableHead>
                    <TableHead>User</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {keys.map(key => (
                    <TableRow key={key.id}>
                      <TableCell className="font-medium">{key.label}</TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">{key.prefix}…</TableCell>
                      <TableCell className="text-muted-foreground text-sm">
                        {members?.find(m => m.user_id === key.user_id)?.email ?? key.user_id}
                      </TableCell>
                      <TableCell><Badge variant={key.revoked ? 'outline' : 'success'}>{key.revoked ? 'REVOKED' : 'ACTIVE'}</Badge></TableCell>
                      <TableCell className="text-muted-foreground text-sm">{formatDate(key.created_at)}</TableCell>
                      <TableCell className="text-right">
                        {!key.revoked && (
                          <Button variant="ghost" size="sm" className="text-destructive hover:bg-destructive/10"
                            onClick={() => revokeKey.mutate({ keyId: key.id })}>
                            Revoke
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-8 text-center text-muted-foreground">No management keys for this org.</div>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="members" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Organization Members</h2>
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
                  {members.map(member => (
                    <TableRow key={member.user_id}>
                      <TableCell className="font-medium">
                        <Link href={`/users/${member.user_id}`} className="hover:text-primary">{member.name}</Link>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{member.email}</TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="icon" className="text-destructive hover:bg-destructive/10"
                          onClick={() => removeMember.mutate({ userId: member.user_id })}>
                          <X className="w-4 h-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-8 text-center text-muted-foreground">No members yet.</div>
            )}
          </Card>
        </TabsContent>
      </Tabs>

      <Modal open={wsOpen} onOpenChange={setWsOpen} title="New Workspace">
        <form onSubmit={e => { e.preventDefault(); createWorkspace.mutate({ data: { name: wsName } }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label>Name</Label>
            <Input required value={wsName} placeholder="staging" onChange={e => setWsName(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setWsOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createWorkspace.isPending}>Create</Button>
          </div>
        </form>
      </Modal>

      <Modal open={memberOpen} onOpenChange={setMemberOpen} title="Add Member">
        <form onSubmit={e => { e.preventDefault(); addMember.mutate({ userId: memberId }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label htmlFor="member">User</Label>
            <Dropdown
              aria-label="User"
              value={memberId}
              onValueChange={setMemberId}
              placeholder="Select a user"
              options={(outsiders ?? []).map(user => ({ value: user.id, label: `${user.name} (${user.email})` }))}
            />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setMemberOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={!memberId || addMember.isPending}>Add</Button>
          </div>
        </form>
      </Modal>

      <Modal open={deleteOpen} onOpenChange={setDeleteOpen} title="Delete Organization"
        description="The org goes with its workspaces, their inference keys, its management keys, memberships and bundles.">
        <div className="space-y-4 pt-4">
          <div className="p-4 bg-destructive/10 text-destructive rounded-md flex items-start gap-3 border border-destructive/20">
            <ShieldAlert className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <p className="text-sm font-medium">Deleting <strong>{org.name}</strong> cannot be undone. The usage it recorded stays.</p>
          </div>
          {deleteError && <p className="text-sm text-destructive">{deleteError}</p>}
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setDeleteOpen(false)}>Cancel</Button>
            <Button variant="destructive" disabled={deleteOrg.isPending} onClick={() => deleteOrg.mutate({ orgId: org.id })}>
              Delete Organization
            </Button>
          </div>
        </div>
      </Modal>

      <Modal open={renameOpen} onOpenChange={setRenameOpen} title="Rename Organization">
        <form onSubmit={e => { e.preventDefault(); rename.mutate({ orgId: org.id, data: { name } }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label>Name</Label>
            <Input required value={name} onChange={e => setName(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setRenameOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={rename.isPending}>Save</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
