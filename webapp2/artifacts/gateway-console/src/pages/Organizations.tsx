import { useState } from 'react';
import { useListOrganizations, useCreateOrganization, getListOrganizationsQueryKey } from '@workspace/api-client-react';
import { Card, Button, Input, Label, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Modal } from '@/components/ui/elements';
import { Building2, Plus, Search } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link } from 'wouter';
import { useQueryClient } from '@tanstack/react-query';

export default function Organizations() {
  const { data: orgs, isLoading } = useListOrganizations();
  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  
  const queryClient = useQueryClient();
  const createOrg = useCreateOrganization({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListOrganizationsQueryKey() });
        setCreateOpen(false);
      }
    }
  });

  const [formData, setFormData] = useState({ name: '', slug: '', description: '' });

  const filteredOrgs = orgs?.filter(o => 
    o.name.toLowerCase().includes(search.toLowerCase()) || 
    o.slug.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Organizations</h1>
          <p className="text-muted-foreground mt-1 text-sm">Manage tenants, their quotas, and member access.</p>
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
                <TableHead>Slug</TableHead>
                <TableHead className="text-right">Workspaces</TableHead>
                <TableHead className="text-right">Members</TableHead>
                <TableHead className="text-right">Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredOrgs.map((org) => (
                <TableRow key={org.id} className="group">
                  <TableCell className="font-medium">
                    <Link href={`/organizations/${org.id}`} className="flex items-center gap-2 hover:text-primary transition-colors">
                      <Building2 className="w-4 h-4 text-muted-foreground group-hover:text-primary" />
                      {org.name}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{org.slug}</TableCell>
                  <TableCell className="text-right font-mono">{org.workspaceCount}</TableCell>
                  <TableCell className="text-right font-mono">{org.memberCount}</TableCell>
                  <TableCell className="text-right text-muted-foreground text-sm">
                    {formatDate(org.createdAt)}
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

      <Modal open={createOpen} onOpenChange={setCreateOpen} title="Create Organization" description="Set up a new top-level tenant.">
        <form onSubmit={(e) => {
          e.preventDefault();
          createOrg.mutate({ data: formData });
        }} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label htmlFor="name">Name</Label>
            <Input id="name" required value={formData.name} onChange={e => setFormData(p => ({ ...p, name: e.target.value, slug: p.slug || e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '-') }))} placeholder="Acme Corp" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="slug">Slug</Label>
            <Input id="slug" required value={formData.slug} onChange={e => setFormData(p => ({ ...p, slug: e.target.value }))} placeholder="acme-corp" className="font-mono text-sm" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="description">Description (Optional)</Label>
            <Input id="description" value={formData.description} onChange={e => setFormData(p => ({ ...p, description: e.target.value }))} />
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
