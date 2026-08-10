import { useState } from 'react';
import * as z from 'zod';
import { useParams } from 'wouter';
import { Plus, KeyRound, RefreshCw, Power, Trash2 } from 'lucide-react';
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
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

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
    { key: 'priority', header: 'Priority', cellClassName: 'text-muted-foreground text-sm', cell: c => c.priority },
    {
      key: 'health',
      header: 'Status',
      cell: c => {
        const { label, variant } = health(c);
        return <Badge variant={variant}>{label}</Badge>;
      },
    },
    {
      key: 'actions',
      header: '',
      headClassName: 'w-px',
      cellClassName: 'w-px',
      cell: c => (
        <TooltipProvider delayDuration={300}>
          <div className="flex items-center gap-1">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button size="icon" variant="ghost" onClick={() => setRotating(c)}>
                  <RefreshCw className="w-4 h-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Rotate key</TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="icon"
                  variant="ghost"
                  className={c.enabled ? '' : 'text-muted-foreground'}
                  onClick={() => updateCredential.mutate({ credentialId: c.id, data: { enabled: !c.enabled } })}>
                  <Power className="w-4 h-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{c.enabled ? 'Disable' : 'Enable'}</TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <ConfirmButton
                    title={`Delete "${c.name}"?`}
                    description="Permanently removes this key. Traffic will fall back to the next available key in priority order. This cannot be undone."
                    confirmLabel="Delete"
                    pending={deleteCredential.isPending}
                    onConfirm={() => deleteCredential.mutate({ credentialId: c.id })}>
                    <Trash2 className="w-4 h-4" />
                  </ConfirmButton>
                </span>
              </TooltipTrigger>
              <TooltipContent>Delete</TooltipContent>
            </Tooltip>
          </div>
        </TooltipProvider>
      ),
    },
  ];

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Provider Keys</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Use your own API keys for this workspace. Keys are tried in priority order — if one fails, the next takes over automatically.
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
          empty="No keys yet. Add one to route this workspace's traffic through your own provider accounts."
          emptyIcon={KeyRound}
        />
      </Card>

      <FormDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        title="Add Provider Key"
        description="Your key is stored encrypted and never exposed again. Paste it once — we handle the rest."
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
                    <div className="flex flex-wrap gap-2">
                      {providers.map(p => {
                        const selected = field.value === p.name;
                        return (
                          <button
                            key={p.id}
                            type="button"
                            onClick={() => field.onChange(p.name)}
                            className={cn(
                              'inline-flex items-center gap-2 rounded border px-3 py-1.5 text-[11px] font-mono font-bold uppercase tracking-wider transition-all',
                              selected
                                ? 'border-primary bg-primary/10 text-primary'
                                : 'border-border bg-background/50 text-muted-foreground hover:border-primary/50 hover:text-foreground'
                            )}>
                            {p.icon ? (
                              <span
                                className="w-4 h-4 shrink-0 [&_svg]:w-full [&_svg]:h-full"
                                dangerouslySetInnerHTML={{ __html: p.icon }}
                              />
                            ) : null}
                            {p.name}
                          </button>
                        );
                      })}
                    </div>
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
                  <FormLabel>Priority</FormLabel>
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
        description="Replaces the existing key immediately. Any in-flight requests will finish with the old key."
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
