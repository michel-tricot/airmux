import { useState } from 'react';
import { useParams } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';
import { useSession } from '@/lib/session';
import { orgScope } from '@/lib/api';
import {
  useListInferenceKeys,
  useCreateInferenceKey,
  useRevokeInferenceKey,
  getListInferenceKeysQueryKey,
} from '@workspace/api-client-react';
import { Card, Button, Input, Label, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Modal, Badge, ConfirmButton } from '@/components/ui/elements';
import { Plus, Ban } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';

export default function WorkspaceApiKeys() {
  const { workspaceRef } = useParams();
  const { orgId } = useSession();
  const queryClient = useQueryClient();
  const scope = orgScope(orgId!);

  const keysKey = [...getListInferenceKeysQueryKey(workspaceRef!), orgId];
  const { data: keys } = useListInferenceKeys(workspaceRef!, { query: { queryKey: keysKey }, request: scope });

  const [keyOpen, setKeyOpen] = useState(false);
  const [keyLabel, setKeyLabel] = useState('');
  const [token, setToken] = useState<string | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: keysKey });
  const createKey = useCreateInferenceKey({
    mutation: { onSuccess: (minted) => { invalidate(); setKeyOpen(false); setKeyLabel(''); setToken(minted.token); } },
    request: scope,
  });
  const revokeKey = useRevokeInferenceKey({ mutation: { onSuccess: invalidate }, request: scope });

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">API Keys</h1>
          <p className="text-muted-foreground mt-1 text-sm">Keys let applications send requests to the models available to this workspace.</p>
        </div>
        <Button onClick={() => setKeyOpen(true)}><Plus className="w-4 h-4 mr-1" /> Generate Key</Button>
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
                        onConfirm={() => revokeKey.mutate({ workspaceRef: workspaceRef!, keyId: key.id })}>
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

      <Modal open={keyOpen} onOpenChange={setKeyOpen} title="Generate Inference Key" description="Keys let applications send requests to the models available to this workspace.">
        <form onSubmit={e => { e.preventDefault(); createKey.mutate({ workspaceRef: workspaceRef!, data: { label: keyLabel } }); }} className="space-y-4 pt-4">
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

      <KeyRevealDialog open={!!token} onOpenChange={(v) => !v && setToken(null)} token={token} />
    </div>
  );
}
