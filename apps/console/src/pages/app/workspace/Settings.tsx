import { useState } from 'react';
import { useParams, useLocation } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';
import { useSession } from '@/lib/session';
import { orgScope } from '@/lib/api';
import {
  useGetWorkspace,
  useUpdateWorkspace,
  useDeleteWorkspace,
  getGetWorkspaceQueryKey,
  getListWorkspacesQueryKey,
} from '@workspace/api-client-react';
import { Card, Button, Input, Label } from '@/components/ui/elements';
import { Trash2 } from 'lucide-react';

export default function WorkspaceSettings() {
  const { workspaceId } = useParams();
  const { orgId } = useSession();
  const queryClient = useQueryClient();
  const [, setLocation] = useLocation();
  const scope = orgScope(orgId!);

  const workspacesKey = [...getListWorkspacesQueryKey(), orgId];
  const { data: workspace, isLoading } = useGetWorkspace(workspaceId!, {
    query: { queryKey: [...getGetWorkspaceQueryKey(workspaceId!), orgId], retry: false },
    request: scope,
  });

  const [name, setName] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const rename = useUpdateWorkspace({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: workspacesKey });
        queryClient.invalidateQueries({ queryKey: [...getGetWorkspaceQueryKey(workspaceId!), orgId] });
        setName(null);
      },
    },
    request: scope,
  });
  const remove = useDeleteWorkspace({
    mutation: {
      onSuccess: () => { queryClient.invalidateQueries({ queryKey: workspacesKey }); setLocation('/org'); },
      onError: (error) => setDeleteError(error.message),
    },
    request: scope,
  });

  if (isLoading) return <div className="p-8 text-center text-muted-foreground font-mono text-sm">LOADING WORKSPACE...</div>;
  if (!workspace) return <div className="p-8 text-center text-destructive">Workspace not found</div>;

  const draft = name ?? workspace.name;

  return (
    <div className="flex-1 p-8 max-w-4xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Workspace Settings</h1>
        <p className="text-muted-foreground mt-1 text-sm font-mono">{workspace.id}</p>
      </div>

      <Card className="p-6 space-y-4">
        <h2 className="text-lg font-semibold">General</h2>
        <form
          onSubmit={e => { e.preventDefault(); rename.mutate({ workspaceId: workspaceId!, data: { name: draft } }); }}
          className="flex items-end gap-3 max-w-md"
        >
          <div className="flex-1 space-y-2">
            <Label htmlFor="ws-name">Workspace name</Label>
            <Input id="ws-name" required value={draft} onChange={e => setName(e.target.value)} />
          </div>
          <Button type="submit" disabled={rename.isPending || draft === workspace.name}>Save</Button>
        </form>
      </Card>

      <Card className="p-6 space-y-4 border-destructive/30">
        <h2 className="text-lg font-semibold text-destructive">Danger zone</h2>
        <p className="text-sm text-muted-foreground">
          Deleting <strong>{workspace.name}</strong> cannot be undone. Its inference keys and its members go with it;
          the usage it recorded stays on the org's bill.
        </p>
        {deleteError && <p className="text-sm text-destructive">{deleteError}</p>}
        {confirming ? (
          <div className="flex items-center gap-2">
            <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate({ workspaceId: workspaceId! })}>
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
    </div>
  );
}
