import { useState } from 'react';
import * as z from 'zod';
import { useParams } from 'wouter';
import { Plus, KeyRound, RotateCw } from 'lucide-react';
import type { ProviderCredentialOut } from '@workspace/api-client-react';
import { useSession } from '@/lib/session';
import {
  useProviderCredentials,
  useProviders,
  useAddCredentialMutation,
  useRotateCredentialMutation,
  useUpdateCredentialMutation,
  useDeleteCredentialMutation,
} from '@/features/credentials/hooks';
import { Button, Card, Badge, Input, ConfirmButton } from '@/components/ui/elements';
import { DataTable, type Column } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';

const addSchema = z.object({
  provider: z.string().min(1, 'Pick a provider'),
  name: z.string().min(1, 'Name is required'),
  value: z.string().min(1, 'Paste the key'),
  priority: z.coerce.number().int().min(1),
});

const rotateSchema = z.object({ value: z.string().min(1, 'Paste the replacement key') });

const HEALTH: Record<string, { label: string; variant: 'success' | 'destructive' | 'secondary' | 'outline' }> = {
  live: { label: 'WORKING', variant: 'success' },
  invalid: { label: 'REJECTED', variant: 'destructive' },
  rate_limited: { label: 'THROTTLED', variant: 'secondary' },
  unknown: { label: 'UNUSED', variant: 'outline' },
};

function health(credential: ProviderCredentialOut) {
  if (!credential.enabled) return { label: 'DISABLED', variant: 'outline' as const };
  return HEALTH[credential.status] ?? { label: credential.status.toUpperCase(), variant: 'outline' as const };
}

export default function WorkspaceByok() {
  const { workspaceRef } = useParams();
  const { orgId } = useSession();

  const credentialsQuery = useProviderCredentials(orgId!, workspaceRef!);
  const taxonomy = useProviders(orgId!);
  const providers = taxonomy.data?.providers ?? [];

  const [addOpen, setAddOpen] = useState(false);
  const [rotating, setRotating] = useState<ProviderCredentialOut | null>(null);

  const addCredential = useAddCredentialMutation(orgId!, workspaceRef!);
  const rotateCredential = useRotateCredentialMutation(orgId!, workspaceRef!);
  const updateCredential = useUpdateCredentialMutation(orgId!, workspaceRef!);
  const deleteCredential = useDeleteCredentialMutation(orgId!, workspaceRef!);

  const columns: Array<Column<ProviderCredentialOut>> = [
    { key: 'provider', header: 'Provider', cellClassName: 'font-medium', cell: c => c.provider_name },
    { key: 'name', header: 'Name', cell: c => c.name },
    {
      key: 'key',
      header: 'Key',
      cellClassName: 'font-mono text-xs text-muted-foreground',
      cell: c => <>…{c.fingerprint}</>,
    },
    { key: 'priority', header: 'Try order', cellClassName: 'text-muted-foreground text-sm', cell: c => c.priority },
    {
      key: 'health',
      header: 'Health',
      cell: c => {
        const { label, variant } = health(c);
        return <Badge variant={variant}>{label}</Badge>;
      },
    },
    {
      key: 'actions',
      header: 'Actions',
      headClassName: 'text-right',
      cellClassName: 'text-right space-x-2',
      cell: c => (
        <>
          <Button size="sm" variant="ghost" onClick={() => setRotating(c)}>
            <RotateCw className="w-3.5 h-3.5 mr-1" /> Rotate
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => updateCredential.mutate({ credentialId: c.id, data: { enabled: !c.enabled } })}>
            {c.enabled ? 'Disable' : 'Enable'}
          </Button>
          <ConfirmButton
            size="sm"
            title={`Delete "${c.name}"?`}
            description="The key is removed from the secret store and requests using it stop at the next bundle. This cannot be undone."
            confirmLabel="Delete"
            pending={deleteCredential.isPending}
            onConfirm={() => deleteCredential.mutate({ credentialId: c.id })}>
            Delete
          </ConfirmButton>
        </>
      ),
    },
  ];

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Provider Keys</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Bring your own provider keys. Requests from this workspace are billed to whichever key answers first.
          </p>
        </div>
        <Button onClick={() => setAddOpen(true)}>
          <Plus className="w-4 h-4 mr-1" /> Add Key
        </Button>
      </div>

      <Card>
        <DataTable
          columns={columns}
          rows={credentialsQuery.data}
          rowKey={c => c.id}
          isLoading={credentialsQuery.isLoading}
          isError={credentialsQuery.isError}
          onRetry={() => credentialsQuery.refetch()}
          empty="No provider keys yet. Without one, this workspace uses the keys the operator configured."
          emptyIcon={KeyRound}
        />
      </Card>

      <FormDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        title="Add Provider Key"
        description="The key goes straight to the secret store. It is never shown again and never stored in the database."
        schema={addSchema}
        defaultValues={{ provider: providers[0]?.name ?? '', name: 'default', value: '', priority: 100 }}
        onSubmit={values => addCredential.mutateAsync({ data: { ...values, workspace: workspaceRef! } })}
        submitLabel="Add Key"
        pending={addCredential.isPending}>
        {form => (
          <>
            <FormField
              control={form.control}
              name="provider"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Provider</FormLabel>
                  <FormControl>
                    <select
                      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      {...field}>
                      {providers.map(p => (
                        <option key={p.id} value={p.name}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input placeholder="e.g. prod or backup" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="value"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>API key</FormLabel>
                  <FormControl>
                    <Input type="password" autoComplete="off" placeholder="sk-..." {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="priority"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Try order</FormLabel>
                  <FormControl>
                    <Input type="number" min={1} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </>
        )}
      </FormDialog>

      <FormDialog
        open={!!rotating}
        onOpenChange={v => !v && setRotating(null)}
        title={rotating ? `Rotate "${rotating.name}"` : 'Rotate'}
        description="The new key replaces the old one everywhere. Data planes pick it up at the next bundle."
        schema={rotateSchema}
        defaultValues={{ value: '' }}
        onSubmit={async values => {
          await rotateCredential.mutateAsync({ credentialId: rotating!.id, data: values });
          setRotating(null);
        }}
        submitLabel="Rotate"
        pending={rotateCredential.isPending}>
        {form => (
          <FormField
            control={form.control}
            name="value"
            render={({ field }) => (
              <FormItem>
                <FormLabel>New API key</FormLabel>
                <FormControl>
                  <Input type="password" autoComplete="off" placeholder="sk-..." {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        )}
      </FormDialog>
    </div>
  );
}
