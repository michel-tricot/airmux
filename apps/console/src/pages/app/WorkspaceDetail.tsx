import { useState } from 'react';
import { useGetWorkspace, useListInferenceKeys, useListWorkspaceMembers, useCreateInferenceKey, useRevokeInferenceKey, getListInferenceKeysQueryKey, getGetWorkspaceQueryKey, getListWorkspaceMembersQueryKey, useListUserWorkspaces, getListUserWorkspacesQueryKey } from '@workspace/api-client-react';
import { Card, Button, Input, Label, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Modal, Badge, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/elements';
import { TerminalSquare, Plus, ArrowLeft, Key, Users } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link, useParams, Redirect } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { useSession } from '@/lib/session';

export default function AppWorkspaceDetail() {
  const { id } = useParams();
  const workspaceId = Number(id);
  const queryClient = useQueryClient();
  const { userId, orgId } = useSession();

  const { data: userWorkspaces, isLoading: loadingUserWorkspaces } = useListUserWorkspaces(userId!, { query: { enabled: !!userId, queryKey: getListUserWorkspacesQueryKey(userId!) }});
  
  const isAuthorized = userWorkspaces?.some(ws => ws.id === workspaceId && ws.orgId === orgId);

  const { data: ws, isLoading: loadingWs } = useGetWorkspace(workspaceId, { query: { enabled: !!workspaceId && isAuthorized, queryKey: getGetWorkspaceQueryKey(workspaceId) } });
  const { data: keys } = useListInferenceKeys(workspaceId, { query: { enabled: !!workspaceId && isAuthorized, queryKey: getListInferenceKeysQueryKey(workspaceId) } });
  const { data: members } = useListWorkspaceMembers(workspaceId, { query: { enabled: !!workspaceId && isAuthorized, queryKey: getListWorkspaceMembersQueryKey(workspaceId) } });

  const [keyOpen, setKeyOpen] = useState(false);
  const [keyForm, setKeyForm] = useState({ name: '' });
  const [createdKey, setCreatedKey] = useState<any>(null);

  const createKey = useCreateInferenceKey({ 
    mutation: { 
      onSuccess: (data) => { 
        queryClient.invalidateQueries({ queryKey: getListInferenceKeysQueryKey(workspaceId) }); 
        queryClient.invalidateQueries({ queryKey: getListUserWorkspacesQueryKey(userId!) });
        setKeyOpen(false); 
        setCreatedKey(data); 
        setKeyForm({name: ''}); 
      } 
    }
  });
  
  const revokeKey = useRevokeInferenceKey({ 
    mutation: { 
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListInferenceKeysQueryKey(workspaceId) });
        queryClient.invalidateQueries({ queryKey: getListUserWorkspacesQueryKey(userId!) });
      }
    }
  });

  if (loadingUserWorkspaces) return <div className="p-8 text-center text-muted-foreground font-mono text-sm">LOADING ACCESS...</div>;
  if (!isAuthorized) return (
    <div className="flex-1 p-8 max-w-5xl mx-auto w-full flex flex-col items-center justify-center space-y-4 animate-in fade-in">
      <div className="w-16 h-16 rounded-full bg-destructive/10 flex items-center justify-center mb-2 text-destructive">
        <TerminalSquare className="w-8 h-8" />
      </div>
      <h2 className="text-xl font-bold">Access Denied</h2>
      <p className="text-muted-foreground">You don't have access to this workspace or it belongs to a different organization.</p>
      <Link href="/app"><Button className="mt-4">Back to Dashboard</Button></Link>
    </div>
  );

  if (loadingWs) return <div className="p-8 text-center text-muted-foreground font-mono text-sm">LOADING...</div>;
  if (!ws) return <div className="p-8 text-center text-destructive">Workspace not found</div>;

  return (
    <div className="flex-1 p-8 max-w-5xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex items-center gap-4 text-sm text-muted-foreground mb-4">
        <Link href="/app" className="hover:text-foreground flex items-center gap-1"><ArrowLeft className="w-4 h-4" /> Back to Workspaces</Link>
      </div>

      <div className="flex items-center gap-4 mb-8">
        <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
          <TerminalSquare className="w-6 h-6 text-primary" />
        </div>
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{ws.name}</h1>
          <p className="text-muted-foreground font-mono text-sm">{ws.slug}</p>
        </div>
      </div>

      <Tabs defaultValue="keys" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="keys" className="gap-2"><Key className="w-4 h-4"/> Inference Keys</TabsTrigger>
          <TabsTrigger value="members" className="gap-2"><Users className="w-4 h-4"/> Members</TabsTrigger>
        </TabsList>

        <TabsContent value="keys" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Inference Keys</h2>
            <Button onClick={() => setKeyOpen(true)} size="sm" className="shadow-sm"><Plus className="w-4 h-4 mr-1"/> Generate Key</Button>
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
                      <TableCell className="font-mono text-xs text-muted-foreground">{key.prefix}***</TableCell>
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
              <div className="p-8 text-center text-muted-foreground">No inference keys generated yet.</div>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="members" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Workspace Members</h2>
          </div>
          <Card>
            {members && members.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Added</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {members.map(member => (
                    <TableRow key={member.userId}>
                      <TableCell className="font-medium flex items-center gap-2">
                        <div className="w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center font-bold text-xs">
                          {member.name.charAt(0)}
                        </div>
                        {member.name}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{member.email}</TableCell>
                      <TableCell className="text-muted-foreground text-sm">{formatDate(member.addedAt)}</TableCell>
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

      <Modal open={keyOpen} onOpenChange={setKeyOpen} title="Generate Inference Key" description="Create a new key to authenticate API requests for this workspace.">
        <form onSubmit={e => { e.preventDefault(); createKey.mutate({ workspaceId, data: keyForm }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label>Key Name</Label>
            <Input required value={keyForm.name} placeholder="e.g. Production Environment" onChange={e => setKeyForm(p => ({...p, name: e.target.value}))} />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setKeyOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createKey.isPending}>Generate</Button>
          </div>
        </form>
      </Modal>

      <KeyRevealDialog open={!!createdKey} onOpenChange={(v) => !v && setCreatedKey(null)} createdKey={createdKey} />
    </div>
  );
}
