import { useState } from 'react';
import * as z from 'zod';
import { Plus, KeyRound, RefreshCw, Power, Trash2 } from 'lucide-react';
import type { ProviderCredentialOut } from '@workspace/api-client-react';
import { useRequiredOrgId } from '@/lib/session';
import {
  useProviderCredentials,
  useProviders,
  useAddCredentialMutation,
  useRotateCredentialMutation,
  useUpdateCredentialMutation,
  useDeleteCredentialMutation,
} from '@/features/credentials/hooks';
import { Button, Card, Badge, Input, ConfirmButton, Label } from '@/components/ui/elements';
import { DataTable, type Column } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useRequiredParam } from '@/lib/route';
import { ProviderIcon } from '@/components/ProviderIcon';
import { PageShell } from '@/components/shared/page-shell';
import { ErrorState } from '@/components/shared/states';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';

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
  const workspaceRef = useRequiredParam('workspaceRef');
  const orgId = useRequiredOrgId();

  const credentialsQuery = useProviderCredentials(orgId, workspaceRef);
  const taxonomy = useProviders(orgId);
  const providers = taxonomy.data?.providers ?? [];

  const [addOpen, setAddOpen] = useState(false);
  const [rotating, setRotating] = useState<ProviderCredentialOut | null>(null);

  const addCredential = useAddCredentialMutation(orgId, workspaceRef);
  const rotateCredential = useRotateCredentialMutation(orgId, workspaceRef);
  const updateCredential = useUpdateCredentialMutation(orgId, workspaceRef);
  const deleteCredential = useDeleteCredentialMutation(orgId, workspaceRef);

  const columns: Array<Column<ProviderCredentialOut>> = [
    { key: 'provider', header: 'Provider', cellClassName: 'font-medium', cell: (c) => c.provider_name },
    { key: 'name', header: 'Name', cell: (c) => c.name },
    {
      key: 'key',
      header: 'Key',
      cellClassName: 'font-mono text-xs text-muted-foreground',
      cell: (c) => <>…{c.fingerprint}</>,
    },
    { key: 'priority', header: 'Priority', cellClassName: 'text-muted-foreground text-sm', cell: (c) => c.priority },
    {
      key: 'health',
      header: 'Status',
      cell: (c) => {
        const { label, variant } = health(c);
        return <Badge variant={variant}>{label}</Badge>;
      },
    },
    {
      key: 'actions',
      header: '',
      headClassName: 'w-px',
      cellClassName: 'w-px',
      cell: (c) => (
        <div className="flex items-center gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button aria-label={`Rotate ${c.name}`} size="icon" variant="ghost" onClick={() => setRotating(c)}>
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
                aria-label={`${c.enabled ? 'Disable' : 'Enable'} ${c.name}`}
                aria-pressed={c.enabled}
                className={c.enabled ? '' : 'text-muted-foreground'}
                onClick={() => updateCredential.mutate({ credentialId: c.id, data: { enabled: !c.enabled } })}
              >
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
                  aria-label={`Delete ${c.name}`}
                  onConfirm={() => deleteCredential.mutateAsync({ credentialId: c.id })}
                >
                  <Trash2 className="w-4 h-4" />
                </ConfirmButton>
              </span>
            </TooltipTrigger>
            <TooltipContent>Delete</TooltipContent>
          </Tooltip>
        </div>
      ),
    },
  ];

  return (
    <PageShell>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Provider Keys</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Use your own API keys for this workspace. Keys are tried in priority order. If one fails, the next takes over automatically.
          </p>
        </div>
        <Button onClick={() => setAddOpen(true)} disabled={taxonomy.isLoading || taxonomy.isError || providers.length === 0}>
          <Plus className="w-4 h-4 mr-1" /> Add Key
        </Button>
      </div>

      {taxonomy.isError && <ErrorState error={taxonomy.error} resource="provider catalog" onRetry={() => taxonomy.refetch()} />}

      <Card>
        <DataTable
          columns={columns}
          rows={credentialsQuery.data}
          rowKey={(c) => c.id}
          isLoading={credentialsQuery.isLoading}
          isError={credentialsQuery.isError}
          error={credentialsQuery.error}
          resource="provider keys"
          onRetry={() => credentialsQuery.refetch()}
          empty="No keys yet. Add one to route this workspace's traffic through your own provider accounts."
          emptyIcon={KeyRound}
        />
      </Card>

      <FormDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        title="Add Provider Key"
        description="Your key is stored encrypted and never exposed again. Paste it once, and we handle the rest."
        schema={addSchema}
        defaultValues={{ provider: providers[0]?.name ?? '', name: 'default', value: '', priority: 100 }}
        onSubmit={(values) => addCredential.mutateAsync({ data: { ...values, workspace: workspaceRef } })}
        submitLabel="Add Key"
        pending={addCredential.isPending}
      >
        {(form) => (
          <>
            <FormField
              control={form.control}
              name="provider"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Provider</FormLabel>
                  <FormControl>
                    <RadioGroup value={field.value} onValueChange={field.onChange} aria-label="Provider" className="flex flex-wrap gap-2">
                      {providers.map((p) => {
                        const optionId = `provider-${p.id}`;
                        return (
                          <div key={p.id} className="relative">
                            <RadioGroupItem id={optionId} value={p.name} className="peer sr-only" />
                            <Label
                              htmlFor={optionId}
                              className="inline-flex h-8 cursor-pointer items-center justify-center gap-2 rounded border border-input bg-background/50 px-3 shadow-sm transition-colors hover:border-primary/50 hover:bg-primary/10 hover:text-primary peer-data-[state=checked]:border-border/50 peer-data-[state=checked]:bg-secondary peer-data-[state=checked]:text-secondary-foreground peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2"
                            >
                              {p.icon ? <ProviderIcon markup={p.icon} /> : null}
                              {p.name}
                            </Label>
                          </div>
                        );
                      })}
                    </RadioGroup>
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
        onOpenChange={(v) => !v && setRotating(null)}
        title={rotating ? `Rotate "${rotating.name}"` : 'Rotate'}
        description="Replaces the existing key immediately. Any in-flight requests will finish with the old key."
        schema={rotateSchema}
        defaultValues={{ value: '' }}
        onSubmit={async (values) => {
          if (!rotating) return;
          await rotateCredential.mutateAsync({ credentialId: rotating.id, data: values });
          setRotating(null);
        }}
        submitLabel="Rotate"
        pending={rotateCredential.isPending}
      >
        {(form) => (
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
    </PageShell>
  );
}
