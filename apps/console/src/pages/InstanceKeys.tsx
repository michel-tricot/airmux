import { useState } from 'react';
import * as z from 'zod';
import { Button, Input } from '@/components/ui/elements';
import { KeyRound, Plus } from 'lucide-react';
import { Link } from 'wouter';
import { useInstanceKeys, useMintInstanceKeyMutation, useRevokeInstanceKeyMutation } from '@/features/keys/hooks';
import { useUsers } from '@/features/users/hooks';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { ApiKeysTable } from '@/components/shared/api-keys-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { ErrorState } from '@/components/shared/states';
import { PageShell } from '@/components/shared/page-shell';

const instanceKeySchema = z.object({
  label: z.string().min(1, 'Label is required').max(80, 'Label must be 80 characters or fewer'),
});

export default function InstanceKeys() {
  const keysQuery = useInstanceKeys();
  const usersQuery = useUsers();
  const usersById = new Map(usersQuery.data?.map((user) => [user.id, user]));
  const mintKey = useMintInstanceKeyMutation();
  const revokeKey = useRevokeInstanceKeyMutation();
  const [mintOpen, setMintOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  return (
    <PageShell>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <KeyRound className="w-6 h-6 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">Instance Keys</h1>
          </div>
          <p className="text-muted-foreground mt-1 text-sm">Mint credentials for instance-level automation and services.</p>
        </div>
        <Button onClick={() => setMintOpen(true)} className="gap-2">
          <Plus className="w-4 h-4" /> Mint Instance Key
        </Button>
      </div>

      {usersQuery.isError && <ErrorState error={usersQuery.error} resource="key owners" onRetry={() => usersQuery.refetch()} />}

      <ApiKeysTable
        keys={keysQuery.data}
        isLoading={keysQuery.isLoading}
        isError={keysQuery.isError}
        error={keysQuery.error}
        onRetry={() => keysQuery.refetch()}
        emptyText="No instance keys have been minted."
        extraColumns={[
          {
            key: 'user',
            header: 'User',
            cellClassName: 'text-sm',
            cell: (key) => {
              const user = usersById.get(key.user_id);
              return user ? (
                <Link href={`/instance/users/${user.id}`} className="hover:text-primary transition-colors">
                  {user.name}
                </Link>
              ) : (
                <span className="font-mono text-xs text-muted-foreground">{key.user_id}</span>
              );
            },
          },
          {
            key: 'scopes',
            header: 'Scopes',
            cellClassName: 'text-muted-foreground text-sm',
            cell: (key) => key.scopes?.join(', ') ?? 'Full authority',
          },
        ]}
        revokeDescription="Services using this key will lose access immediately. This cannot be undone."
        onRevoke={(key) => revokeKey.mutateAsync({ keyId: key.id })}
        revokePending={revokeKey.isPending}
      />

      <FormDialog
        open={mintOpen}
        onOpenChange={setMintOpen}
        title="Mint an instance key"
        description="Use a clear label so you can identify this credential later. The secret is shown only once."
        schema={instanceKeySchema}
        defaultValues={{ label: '' }}
        onSubmit={async (values) => {
          const minted = await mintKey.mutateAsync({ data: values });
          setToken(minted.token);
        }}
        submitLabel="Mint key"
        pendingLabel="Minting..."
        pending={mintKey.isPending}
      >
        {(form) => (
          <FormField
            control={form.control}
            name="label"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Label</FormLabel>
                <FormControl>
                  <Input placeholder="e.g. production-worker" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        )}
      </FormDialog>

      <KeyRevealDialog open={!!token} onOpenChange={(open) => !open && setToken(null)} token={token} />
    </PageShell>
  );
}
