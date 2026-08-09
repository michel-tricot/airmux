import { useGetUser, useListUserOrganizations, useDeleteUser, getListUsersQueryKey, getGetUserQueryKey, getListUserOrganizationsQueryKey } from '@workspace/api-client-react';
import { Card, Button, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Modal, Badge } from '@/components/ui/elements';
import { ArrowLeft, Building2, UserCircle, Trash2 } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link, useParams, useLocation } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

export default function UserDetail() {
  const { id } = useParams();
  const userId = Number(id);
  const [, setLocation] = useLocation();
  const queryClient = useQueryClient();

  const { data: user, isLoading: loadingUser } = useGetUser(userId, { query: { enabled: !!userId, queryKey: getGetUserQueryKey(userId) } });
  const { data: orgs } = useListUserOrganizations(userId, { query: { enabled: !!userId, queryKey: getListUserOrganizationsQueryKey(userId) } });

  const [deleteOpen, setDeleteOpen] = useState(false);
  const deleteUser = useDeleteUser({ mutation: { onSuccess: () => { queryClient.invalidateQueries({ queryKey: getListUsersQueryKey() }); setLocation('/users'); } } });

  if (loadingUser) return <div className="p-8 text-center">Loading...</div>;
  if (!user) return <div className="p-8 text-center text-destructive">User not found</div>;

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
          </div>
        </div>
        <Button variant="outline" className="text-destructive hover:bg-destructive hover:text-destructive-foreground" onClick={() => setDeleteOpen(true)}>
          <Trash2 className="w-4 h-4 mr-2" /> Delete User
        </Button>
      </div>

      <div className="mt-8">
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <Building2 className="w-5 h-5 text-muted-foreground" />
          Organization Memberships
        </h2>
        <Card>
          {orgs && orgs.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Organization</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead className="text-right">Joined</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {orgs.map(membership => (
                  <TableRow key={membership.orgId}>
                    <TableCell className="font-medium">
                      <Link href={`/organizations/${membership.orgId}`} className="hover:text-primary">
                        {membership.orgName}
                      </Link>
                      <div className="text-xs text-muted-foreground font-mono mt-0.5">{membership.orgSlug}</div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="uppercase text-[10px] tracking-wider">{membership.role}</Badge>
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground text-sm">
                      {formatDate(membership.joinedAt)}
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

      <Modal open={deleteOpen} onOpenChange={setDeleteOpen} title="Delete User" description="This action will remove the user globally and from all organizations.">
        <div className="space-y-4 pt-4">
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setDeleteOpen(false)}>Cancel</Button>
            <Button variant="destructive" onClick={() => deleteUser.mutate({ userId })}>Delete Forever</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
