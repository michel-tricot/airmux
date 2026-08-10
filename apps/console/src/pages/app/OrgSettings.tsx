import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  useListManagementKeys,
  useMintOrgManagementKey,
  useRevokeManagementKey,
  useListBundles,
  useCompileBundle,
  useListOrgUsers,
  useListActivity,
  getListManagementKeysQueryKey,
  getListBundlesQueryKey,
  getListOrgUsersQueryKey,
  getListActivityQueryKey,
} from '@workspace/api-client-react';
import { useSession } from '@/lib/session';
import { orgScope } from '@/lib/api';
import { Card, Button, Input, Label, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Modal, Badge, Tabs, TabsList, TabsTrigger, TabsContent, ConfirmButton } from '@/components/ui/elements';
import { Plus, Key, Settings, Package, RefreshCw, Users, Activity, Ban } from 'lucide-react';
import { formatDate, formatRelative } from '@/lib/format';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';

export default function AppOrgSettings() {
  const { orgId } = useSession();
  const queryClient = useQueryClient();
  const scope = orgScope(orgId!);

  const keysKey = [...getListManagementKeysQueryKey(), orgId];
  const bundlesKey = [...getListBundlesQueryKey(), orgId];
  const membersKey = [...getListOrgUsersQueryKey(), orgId];
  const activityKey = [...getListActivityQueryKey({ limit: 50 }), orgId];

  const { data: keys } = useListManagementKeys({ query: { queryKey: keysKey }, request: scope });
  const { data: bundles } = useListBundles({ query: { queryKey: bundlesKey }, request: scope });
  const { data: members } = useListOrgUsers({ query: { queryKey: membersKey }, request: scope });
  const { data: activity } = useListActivity({ limit: 50 }, { query: { queryKey: activityKey }, request: scope });

  const [keyOpen, setKeyOpen] = useState(false);
  const [label, setLabel] = useState('');
  const [token, setToken] = useState<string | null>(null);

  const mintKey = useMintOrgManagementKey({
    mutation: {
      onSuccess: (minted) => {
        queryClient.invalidateQueries({ queryKey: keysKey });
        setKeyOpen(false);
        setLabel('');
        setToken(minted.token);
      },
    },
    request: scope,
  });

  const revokeKey = useRevokeManagementKey({
    mutation: { onSuccess: () => queryClient.invalidateQueries({ queryKey: keysKey }) },
    request: scope,
  });

  const compile = useCompileBundle({
    mutation: { onSuccess: () => queryClient.invalidateQueries({ queryKey: bundlesKey }) },
    request: scope,
  });

  return (
    <div className="flex-1 p-8 max-w-5xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex items-center gap-4 mb-8">
        <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
          <Settings className="w-6 h-6 text-primary" />
        </div>
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Organization Settings</h1>
          <p className="text-muted-foreground mt-1 text-sm">Management keys for this API, and the signed bundles data planes poll.</p>
        </div>
      </div>

      <Tabs defaultValue="keys" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="keys" className="gap-2"><Key className="w-4 h-4" /> Management Keys</TabsTrigger>
          <TabsTrigger value="bundles" className="gap-2"><Package className="w-4 h-4" /> Bundles</TabsTrigger>
          <TabsTrigger value="members" className="gap-2"><Users className="w-4 h-4" /> Members</TabsTrigger>
          <TabsTrigger value="activity" className="gap-2"><Activity className="w-4 h-4" /> Activity</TabsTrigger>
        </TabsList>

        <TabsContent value="keys" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Management Keys</h2>
            <Button onClick={() => setKeyOpen(true)} size="sm" className="shadow-sm"><Plus className="w-4 h-4 mr-1" /> Generate Key</Button>
          </div>
          <Card>
            {keys && keys.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Label</TableHead>
                    <TableHead>Key</TableHead>
                    <TableHead>Scopes</TableHead>
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
                      <TableCell className="font-mono text-xs text-muted-foreground">{key.scopes?.join(', ') ?? 'all'}</TableCell>
                      <TableCell><Badge variant={key.revoked ? 'outline' : 'success'}>{key.revoked ? 'REVOKED' : 'ACTIVE'}</Badge></TableCell>
                      <TableCell className="text-muted-foreground text-sm">{formatDate(key.created_at)}</TableCell>
                      <TableCell className="text-right">
                        {!key.revoked && (
                          <ConfirmButton size="sm"
                            title={`Revoke "${key.label}"?`}
                            description="Requests signed with this management key will stop working immediately. This cannot be undone."
                            confirmLabel="Revoke key"
                            pending={revokeKey.isPending}
                            onConfirm={() => revokeKey.mutate({ keyId: key.id })}>
                            <Ban className="w-4 h-4 mr-1" /> Revoke
                          </ConfirmButton>
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

        <TabsContent value="bundles" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Policy Bundles</h2>
            <Button onClick={() => compile.mutate()} size="sm" disabled={compile.isPending}>
              <RefreshCw className="w-4 h-4 mr-1" /> {compile.isPending ? 'Compiling...' : 'Compile Now'}
            </Button>
          </div>
          <Card>
            {bundles && bundles.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Version</TableHead>
                    <TableHead>Bundle ID</TableHead>
                    <TableHead>Issued</TableHead>
                    <TableHead className="text-right">Expires</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[...bundles].reverse().map(bundle => (
                    <TableRow key={bundle.id}>
                      <TableCell className="font-mono font-medium">v{bundle.version}</TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">{bundle.id}</TableCell>
                      <TableCell className="text-muted-foreground text-sm">{formatDate(bundle.issued_at)}</TableCell>
                      <TableCell className="text-right text-muted-foreground text-sm">{formatDate(bundle.expires_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-8 text-center text-muted-foreground">No bundles compiled for this org yet.</div>
            )}
          </Card>
        </TabsContent>
        <TabsContent value="members" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Organization Members</h2>
          </div>
          <Card>
            {members && members.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead className="text-right">Kind</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {members.map(member => (
                    <TableRow key={member.user_id}>
                      <TableCell className="font-medium flex items-center gap-2">
                        <div className="w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center font-bold text-xs">
                          {member.name.charAt(0)}
                        </div>
                        {member.name}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{member.email}</TableCell>
                      <TableCell className="text-right">
                        <Badge variant={member.service_account ? 'secondary' : 'outline'}>
                          {member.service_account ? 'SERVICE' : 'HUMAN'}
                        </Badge>
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
        <TabsContent value="activity" className="space-y-4 mt-0">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Recent Changes</h2>
          </div>
          <Card>
            {activity && activity.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Action</TableHead>
                    <TableHead>Resource</TableHead>
                    <TableHead>Actor</TableHead>
                    <TableHead className="text-right">When</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {activity.map(entry => (
                    <TableRow key={entry.id}>
                      <TableCell>
                        <Badge variant={entry.action === 'delete' ? 'destructive' : entry.action === 'create' ? 'success' : 'secondary'}
                          className="font-mono">
                          {entry.action}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-medium">
                        {entry.table_name}
                        <div className="text-xs text-muted-foreground font-mono">{entry.record_id}</div>
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {members?.find(m => m.user_id === entry.user_id)?.email ?? entry.user_id}
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground text-sm">{formatRelative(entry.occurred_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-8 text-center text-muted-foreground">Nothing has changed in this org yet.</div>
            )}
          </Card>
        </TabsContent>
      </Tabs>

      <Modal open={keyOpen} onOpenChange={setKeyOpen} title="Generate Management Key" description="Keys carry the acting user's access to this API for scripts and the CLI.">
        <form onSubmit={e => { e.preventDefault(); mintKey.mutate({ data: { label } }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label>Label</Label>
            <Input required value={label} placeholder="e.g. ci-deploy" onChange={e => setLabel(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setKeyOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={mintKey.isPending}>Generate</Button>
          </div>
        </form>
      </Modal>

      <KeyRevealDialog open={!!token} onOpenChange={(v) => !v && setToken(null)} token={token} />
    </div>
  );
}
