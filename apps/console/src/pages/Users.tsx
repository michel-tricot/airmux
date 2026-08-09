import { useState } from 'react';
import { useListUsers, useCreateUser, getListUsersQueryKey } from '@workspace/api-client-react';
import { Card, Button, Input, Label, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Modal, Badge } from '@/components/ui/elements';
import { Users, Plus, Search } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';

export default function UsersList() {
  const { data: users, isLoading } = useListUsers();
  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [formData, setFormData] = useState({ name: '', email: '' });
  
  const queryClient = useQueryClient();
  const createUser = useCreateUser({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListUsersQueryKey() });
        setCreateOpen(false);
        setFormData({ name: '', email: '' });
      }
    }
  });

  const filteredUsers = users?.filter(u => 
    u.name.toLowerCase().includes(search.toLowerCase()) || 
    u.email.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Global Users</h1>
          <p className="text-muted-foreground mt-1 text-sm">Top-level identity management across all organizations.</p>
        </div>
        <Button onClick={() => setCreateOpen(true)} className="gap-2">
          <Plus className="w-4 h-4" /> Add User
        </Button>
      </div>

      <Card>
        <div className="p-4 border-b border-border flex items-center gap-4">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input 
              placeholder="Search users..." 
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>
        </div>
        
        {isLoading ? (
          <div className="p-8 text-center text-muted-foreground font-mono text-sm">LOADING...</div>
        ) : filteredUsers && filteredUsers.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>User</TableHead>
                <TableHead>Email</TableHead>
                <TableHead className="text-right">Organizations</TableHead>
                <TableHead className="text-right">Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredUsers.map((user) => (
                <TableRow key={user.id} className="group">
                  <TableCell className="font-medium">
                    <Link href={`/users/${user.id}`} className="flex items-center gap-2 hover:text-primary transition-colors">
                      <div className="w-6 h-6 rounded-full bg-muted flex items-center justify-center text-xs font-bold text-muted-foreground">
                        {user.name.charAt(0)}
                      </div>
                      {user.name}
                    </Link>
                  </TableCell>
                  <TableCell className="text-muted-foreground text-sm">{user.email}</TableCell>
                  <TableCell className="text-right">
                    <Badge variant="secondary" className="font-mono">{user.orgCount}</Badge>
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground text-sm">
                    {formatDate(user.createdAt)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="p-12 text-center text-muted-foreground">
            <Users className="w-12 h-12 mx-auto mb-4 opacity-20" />
            <p>No users found.</p>
          </div>
        )}
      </Card>

      <Modal open={createOpen} onOpenChange={setCreateOpen} title="Add User">
        <form onSubmit={(e) => {
          e.preventDefault();
          createUser.mutate({ data: formData });
        }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label htmlFor="name">Full Name</Label>
            <Input id="name" required value={formData.name} onChange={e => setFormData(p => ({ ...p, name: e.target.value }))} placeholder="Jane Doe" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" required value={formData.email} onChange={e => setFormData(p => ({ ...p, email: e.target.value }))} placeholder="jane@example.com" />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createUser.isPending}>
              {createUser.isPending ? 'Adding...' : 'Add User'}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
