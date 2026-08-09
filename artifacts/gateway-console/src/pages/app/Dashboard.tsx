import { useListUserWorkspaces, getListUserWorkspacesQueryKey } from '@workspace/api-client-react';
import { useSession } from '@/lib/session';
import { Card, Badge, Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from '@/components/ui/elements';
import { TerminalSquare, FolderGit2 } from 'lucide-react';
import { Link } from 'wouter';
import { formatDate } from '@/lib/format';

export default function AppDashboard() {
  const { userId, orgId } = useSession();
  const { data: workspaces, isLoading } = useListUserWorkspaces(userId!, { query: { enabled: !!userId, queryKey: getListUserWorkspacesQueryKey(userId!) }});

  const activeWorkspaces = workspaces?.filter(w => w.orgId === orgId);

  return (
    <div className="flex-1 p-8 max-w-5xl mx-auto w-full space-y-6 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Organization Overview</h1>
        <p className="text-muted-foreground mt-1 text-sm">Select a workspace to manage its keys and access.</p>
      </div>

      <Card>
        <div className="p-4 border-b border-border bg-muted/20">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <TerminalSquare className="w-5 h-5 text-muted-foreground" />
            Your Workspaces
          </h2>
        </div>
        
        {isLoading ? (
          <div className="py-12 text-center text-muted-foreground font-mono text-sm">LOADING WORKSPACES...</div>
        ) : activeWorkspaces && activeWorkspaces.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Workspace</TableHead>
                <TableHead>Slug</TableHead>
                <TableHead className="text-right">Keys</TableHead>
                <TableHead className="text-right">Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {activeWorkspaces.map(ws => (
                <TableRow key={ws.id} className="group">
                  <TableCell className="font-medium">
                    <Link href={`/app/workspaces/${ws.id}`} className="flex items-center gap-2 hover:text-primary transition-colors">
                      <FolderGit2 className="w-4 h-4 text-muted-foreground group-hover:text-primary" />
                      {ws.name}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{ws.slug}</TableCell>
                  <TableCell className="text-right">
                    <Badge variant="secondary" className="font-mono text-[10px]">{ws.inferenceKeyCount}</Badge>
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground text-sm">
                    {formatDate(ws.createdAt)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="text-center p-12 text-muted-foreground">
            <TerminalSquare className="w-12 h-12 mx-auto mb-4 opacity-20" />
            <p>You don't have access to any workspaces in this organization.</p>
          </div>
        )}
      </Card>
    </div>
  );
}
