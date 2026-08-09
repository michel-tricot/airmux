import { useState } from 'react';
import {
  useGetUser,
  useDeleteUser,
  useListOrgs,
  addOrgUser,
  removeOrgUser,
  getGetUserQueryKey,
  getListUsersQueryKey,
} from '@workspace/api-client-react';
import { useMutation } from '@tanstack/react-query';
import { orgScope } from '@/lib/api';
import { Card, Button, Label, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Modal, Badge } from '@/components/ui/elements';
import { ArrowLeft, Building2, Plus, X, Trash2 } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link, useParams, useLocation } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';

export default function UserDetail() {
  const { userId } = useParams();
  const [, setLocation] = useLocation();
  const queryClient = useQueryClient();

  const { data: user, isLoading } = useGetUser(userId!, { query: { queryKey: getGetUserQueryKey(userId!), retry: false } });
  const { data: orgs } = useListOrgs();

  const [addOpen, setAddOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [orgId, setOrgId] = useState('');

  // Membership is org-scoped: the org arrives in the header, and this page grants across orgs,
  // so the calls go through the generated functions where the scope is per call rather than
  // through the hooks, which fix their headers once.
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: getListUsersQueryKey() });
    queryClient.invalidateQueries({ queryKey: getGetUserQueryKey(userId!) });
  };
  const addMember = useMutation({
    mutationFn: (target: { userId: string; orgId: string }) => addOrgUser(target.userId, orgScope(target.orgId)),
    onSuccess: () => { invalidate(); setAddOpen(false); setOrgId(''); },
  });
  const removeMember = useMutation({
    mutationFn: (target: { userId: string; orgId: string }) => removeOrgUser(target.userId, orgScope(target.orgId)),
    onSuccess: invalidate,
  });

  const deleteUser = useDeleteUser({
    mutation: {
      onSuccess: () => { queryClient.invalidateQueries({ queryKey: getListUsersQueryKey() }); setLocation('/users'); },
      onError: (error) => setDeleteError(error.message),
    },
  });

  if (isLoading) return <div className="p-8 text-center text-muted-foreground font-mono text-sm">LOADING...</div>;
  if (!user) return <div className="p-8 text-center text-destructive">User not found</div>;

  const memberships = orgs?.filter(o => user.orgs.includes(o.id));
  const available = orgs?.filter(o => !user.orgs.includes(o.id));

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex items-center gap-4 text-sm text-muted-foreground mb-4">
        <Link href="/users" className="hover:text-foreground flex items-center gap-1"><ArrowLeft className="w-4 h-4" /> Back to Users</Link>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="w-16 h-16 rounded-full bg-primary flex items-center justify-center text-2xl font-bold text-primary-foreground shadow-lg">
            {user.name.charAt(0)}
          </div>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{user.name}</h1>
            <p className="text-muted-foreground text-sm">{user.email}</p>
            <p className="text-muted-foreground font-mono text-xs mt-1">{user.id}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant={user.service_account ? 'secondary' : 'outline'}>
            {user.service_account ? 'SERVICE ACCOUNT' : 'HUMAN'}
          </Badge>
          <Button variant="outline" className="text-destructive hover:bg-destructive hover:text-destructive-foreground"
            onClick={() => { setDeleteError(null); setDeleteOpen(true); }}>
            <Trash2 className="w-4 h-4 mr-2" /> Delete
          </Button>
        </div>
      </div>

      <div className="mt-8">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Building2 className="w-5 h-5 text-muted-foreground" />
            Organization Memberships
          </h2>
          <Button onClick={() => setAddOpen(true)} size="sm"><Plus className="w-4 h-4 mr-1" /> Add to Organization</Button>
        </div>
        <Card>
          {memberships && memberships.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Organization</TableHead>
                  <TableHead>ID</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {memberships.map(org => (
                  <TableRow key={org.id}>
                    <TableCell className="font-medium">
                      <Link href={`/organizations/${org.id}`} className="hover:text-primary">{org.name}</Link>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{org.id}</TableCell>
                    <TableCell className="text-muted-foreground text-sm">{formatDate(org.created_at)}</TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="icon" className="text-destructive hover:bg-destructive/10"
                        onClick={() => removeMember.mutate({ userId: user.id, orgId: org.id })}>
                        <X className="w-4 h-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="p-8 text-center text-muted-foreground">User does not belong to any organizations.</div>
          )}
        </Card>
      </div>

      <Modal open={deleteOpen} onOpenChange={setDeleteOpen} title="Delete User"
        description="Their sign-in identities, sessions and personal keys go with them.">
        <div className="space-y-4 pt-4">
          <p className="text-sm text-muted-foreground">
            A user who still holds memberships, owns a personal org, or minted inference keys is refused; clear those first.
          </p>
          {deleteError && <p className="text-sm text-destructive">{deleteError}</p>}
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setDeleteOpen(false)}>Cancel</Button>
            <Button variant="destructive" disabled={deleteUser.isPending} onClick={() => deleteUser.mutate({ userId: user.id })}>
              Delete User
            </Button>
          </div>
        </div>
      </Modal>

      <Modal open={addOpen} onOpenChange={setAddOpen} title="Add to Organization">
        <form onSubmit={e => { e.preventDefault(); addMember.mutate({ userId: user.id, orgId }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label htmlFor="org">Organization</Label>
            <select id="org" required value={orgId} onChange={e => setOrgId(e.target.value)}
              className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm">
              <option value="" disabled>Select an organization</option>
              {available?.map(org => (
                <option key={org.id} value={org.id}>{org.name}</option>
              ))}
            </select>
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={addMember.isPending}>Add</Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
