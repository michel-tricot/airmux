import { useState } from 'react';
import { useListOrgs, useCreateOrg, getListOrgsQueryKey } from '@workspace/api-client-react';
import { Card, Button, Input, Label, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Modal, Badge } from '@/components/ui/elements';
import { Building2, Plus, Search } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';

export default function Organizations() {
  const { data: orgs, isLoading } = useListOrgs();
  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState('');

  const queryClient = useQueryClient();
  const createOrg = useCreateOrg({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListOrgsQueryKey() });
        setCreateOpen(false);
        setName('');
      },
    },
  });

  const filteredOrgs = orgs?.filter(o => o.name.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Organizations</h1>
          <p className="text-muted-foreground mt-1 text-sm">Organizations group your keys, policies, and usage.</p>
        </div>
        <Button onClick={() => setCreateOpen(true)} className="gap-2">
          <Plus className="w-4 h-4" /> New Organization
        </Button>
      </div>

      <Card>
        <div className="p-4 border-b border-border flex items-center gap-4">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search organizations..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>
        </div>

        {isLoading ? (
          <div className="p-8 text-center text-muted-foreground font-mono text-sm">LOADING...</div>
        ) : filteredOrgs && filteredOrgs.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Organization Name</TableHead>
                <TableHead>ID</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead className="text-right">Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredOrgs.map((org) => (
                <TableRow key={org.id} className="group">
                  <TableCell className="font-medium">
                    <Link href={`/instance/organizations/${org.id}`} className="flex items-center gap-2 hover:text-primary transition-colors">
                      <Building2 className="w-4 h-4 text-muted-foreground group-hover:text-primary" />
                      {org.name}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{org.id}</TableCell>
                  <TableCell>
                    <Badge variant={org.personal_for ? 'secondary' : 'outline'}>{org.personal_for ? 'PERSONAL' : 'SHARED'}</Badge>
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground text-sm">
                    {formatDate(org.created_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="p-12 text-center text-muted-foreground">
            <Building2 className="w-12 h-12 mx-auto mb-4 opacity-20" />
            <p>No organizations found.</p>
          </div>
        )}
      </Card>

      <Modal open={createOpen} onOpenChange={setCreateOpen} title="Create Organization" description="Set up a new organization.">
        <form onSubmit={(e) => { e.preventDefault(); createOrg.mutate({ data: { name } }); }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label htmlFor="name">Name</Label>
            <Input id="name" required value={name} onChange={e => setName(e.target.value)} placeholder="Acme Corp" />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={createOrg.isPending}>
              {createOrg.isPending ? 'Creating...' : 'Create Organization'}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
