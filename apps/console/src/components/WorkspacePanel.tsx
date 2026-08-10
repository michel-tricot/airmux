import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  useGetWorkspace,
  useDeleteWorkspace,
  useUpdateWorkspace,
  useListInferenceKeys,
  useCreateInferenceKey,
  useRevokeInferenceKey,
  useListMembers,
  useAddMember,
  useRemoveMember,
  useListOrgUsers,
  getListWorkspacesQueryKey,
  getListInferenceKeysQueryKey,
  getListMembersQueryKey,
  getListOrgUsersQueryKey,
  getGetWorkspaceQueryKey,
} from '@workspace/api-client-react';
import { Card, Button, Input, Label, Dropdown, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Modal, Badge, Tabs, TabsList, TabsTrigger, TabsContent, ConfirmButton } from '@/components/ui/elements';
import { TerminalSquare, Plus, ArrowLeft, Key, Users, UserMinus, Ban, Pencil, Trash2 } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link, useLocation } from 'wouter';
import { orgScope } from '@/lib/api';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';

interface WorkspacePanelProps {
  orgId: string;
  workspaceRef: string;
  backHref: string;
  backLabel: string;
}

export function WorkspacePanel({ orgId, workspaceRef, backHref, backLabel }: WorkspacePanelProps) {
  const queryClient = useQueryClient();
  const [, setLocation] = useLocation();
  const scope = orgScope(orgId);

  const workspacesKey = [...getListWorkspacesQueryKey(), orgId];
  const keysKey = [...getListInferenceKeysQueryKey(workspaceRef), orgId];
  const membersKey = [...getListMembersQueryKey(workspaceRef), orgId];
  const orgUsersKey = [...getListOrgUsersQueryKey(), orgId];

  const { data: workspace, isLoading } = useGetWorkspace(workspaceRef, {
    query: { queryKey: [...getGetWorkspaceQueryKey(workspaceRef), orgId], retry: false },
    request: scope,
  });

  const { data: keys } = useListInferenceKeys(workspaceRef, { query: { queryKey: keysKey }, request: scope });
  const { data: members } = useListMembers(workspaceRef, { query: { queryKey: membersKey }, request: scope });

  // Workspace members are user ids alone, and members are drawn from the org, so the org roster
  // both names them and supplies the candidates.
  const { data: orgUsers } = useListOrgUsers({ query: { queryKey: orgUsersKey }, request: scope });
  const candidates = orgUsers?.filter(u => !members?.some(m => m.user_id === u.user_id));

  const [keyOpen, setKeyOpen] = useState(false);
  const [memberOpen, setMemberOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [keyLabel, setKeyLabel] = useState('');
  const [memberId, setMemberId] = useState('');
  const [name, setName] = useState('');
  const [token, setToken] = useState<string | null>(null);

  const invalidate = (queryKey: unknown[]) => queryClient.invalidateQueries({ queryKey });

  const createKey = useCreateInferenceKey({
    mutation: { onSuccess: (minted) => { invalidate(keysKey); setKeyOpen(false); setKeyLabel(''); setToken(minted.token); } },
    request: scope,
  });
  const revokeKey = useRevokeInferenceKey({ mutation: { onSuccess: () => invalidate(keysKey) }, request: scope });
  const addMember = useAddMember({
    mutation: { onSuccess: () => { invalidate(membersKey); setMemberOpen(false); setMemberId(''); } },
    request: scope,
  });
  const removeMember = useRemoveMember({ mutation: { onSuccess: () => invalidate(membersKey) }, request: scope });
  const rename = useUpdateWorkspace({
    mutation: {
      onSuccess: () => {
        invalidate(workspacesKey);
        invalidate([...getGetWorkspaceQueryKey(workspaceRef), orgId]);
        setRenameOpen(false);
      },
    },
    request: scope,
  });
  const remove = useDeleteWorkspace({
    mutation: {
      onSuccess: () => { invalidate(workspacesKey); setLocation(backHref); },
      onError: () => setDeleteError('We couldn’t delete this workspace. Please try again.'),
    },
    request: scope,
  });

  if (isLoading) return <div className="p-8 text-center text-muted-foreground font-mono text-sm">Loading workspace...</div>;
  if (!workspace) return <div className="p-8 text-center text-destructive">Workspace not found</div>;

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
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
            <p className="text-muted-foreground font-mono text-sm">{workspace.slug}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => { setName(workspace.name); setRenameOpen(true); }}>
            <Pencil className="w-4 h-4 mr-2" /> Rename
          </Button>
          <Button variant="outline" className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
            onClick={() => { setDeleteError(null); setDeleteOpen(true); }}>
            <Trash2 className="w-4 h-4 mr-2" /> Delete
          </Button>
        </div>
      </div>

      <Tabs defaultValue="keys" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="keys" className="gap-2"><Key className="w-4 h-4" /> Inference Keys</TabsTrigger>
          <TabsTrigger value="members" className="gap-2"><Users className="w-4 h-4" /> Members</TabsTrigger>
        </TabsList>

        <TabsContent value="keys" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Inference Keys</h2>
            <Button onClick={() => setKeyOpen(true)} size="sm"><Plus className="w-4 h-4 mr-1" /> Generate Key</Button>
          </div>
          <Card>
            {keys && keys.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Label</TableHead>
                    <TableHead>Key</TableHead>
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
                      <TableCell><Badge variant={key.revoked ? 'outline' : 'success'}>{key.revoked ? 'REVOKED' : 'ACTIVE'}</Badge></TableCell>
                      <TableCell className="text-muted-foreground text-sm">{formatDate(key.created_at)}</TableCell>
                      <TableCell className="text-right">
                        {!key.revoked && (
                          <ConfirmButton size="sm"
                            title={`Revoke "${key.label}"?`}
                            description="Requests using this inference key will stop working immediately. This cannot be undone."
                            confirmLabel="Revoke key"
                            pending={revokeKey.isPending}
                            onConfirm={() => revokeKey.mutate({ workspaceRef, keyId: key.id })}>
                            <Ban className="w-4 h-4 mr-1" /> Revoke
                          </ConfirmButton>
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
                            onConfirm={() => removeMember.mutate({ workspaceRef, userId: member.user_id })}>
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
        </TabsContent>
      </Tabs>

      <Modal open={keyOpen} onOpenChange={setKeyOpen} title="Generate Inference Key" description="Keys let applications send requests to the models available to this workspace.">
        <form onSubmit={e => { e.preventDefault(); createKey.mutate({ workspaceRef, data: { label: keyLabel } }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label>Label</Label>
            <Input required value={keyLabel} placeholder="e.g. chatbot-prod" onChange={e => setKeyLabel(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setKeyOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createKey.isPending}>Generate</Button>
          </div>
        </form>
      </Modal>

      <Modal open={memberOpen} onOpenChange={setMemberOpen} title="Add Member" description="Members are drawn from the org; the user must already belong to it.">
        <form onSubmit={e => { e.preventDefault(); addMember.mutate({ workspaceRef, userId: memberId }); }} className="space-y-4 pt-4">
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

      <Modal open={deleteOpen} onOpenChange={setDeleteOpen} title="Delete Workspace"
        description="Its inference keys and its members go with it.">
        <div className="space-y-4 pt-4">
          <p className="text-sm text-muted-foreground">
            Deleting <strong>{workspace.name}</strong> cannot be undone. Usage already recorded remains on the organization’s bill.
          </p>
          {deleteError && <p className="text-sm text-destructive">{deleteError}</p>}
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setDeleteOpen(false)}>Cancel</Button>
            <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate({ workspaceRef })}>
              Delete Workspace
            </Button>
          </div>
        </div>
      </Modal>

      <Modal open={renameOpen} onOpenChange={setRenameOpen} title="Rename Workspace">
        <form onSubmit={e => { e.preventDefault(); rename.mutate({ workspaceRef, data: { name } }); }} className="space-y-4 pt-4">
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

      <KeyRevealDialog open={!!token} onOpenChange={(v) => !v && setToken(null)} token={token} />
    </div>
  );
}
