import { useState } from 'react';
import * as z from 'zod';
import { Card, Button, Badge } from '@/components/ui/elements';
import { KeyRound, Plus } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { Link } from 'wouter';
import {
  useInstanceKeys,
  useMintInstanceKeyMutation,
  useRevokeInstanceKeyMutation,
} from '@/features/keys/hooks';
import { useUsers } from '@/features/users/hooks';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { DataTable } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/elements';
import { ConfirmButton } from '@/components/ui/elements';

const instanceKeySchema = z.object({
  label: z.string().min(1, 'Label is required').max(80, 'Label must be 80 characters or fewer'),
});

export default function InstanceKeys() {
  const keysQuery = useInstanceKeys();
  const usersQuery = useUsers();
  const mintKey = useMintInstanceKeyMutation();
  const revokeKey = useRevokeInstanceKeyMutation();
  const [mintOpen, setMintOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <KeyRound className="w-6 h-6 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">Instance Keys</h1>
          </div>
          <p className="text-muted-foreground mt-1 text-sm">
            Mint credentials for instance-level automation and services.
          </p>
        </div>
        <Button onClick={() => setMintOpen(true)} className="gap-2">
          <Plus className="w-4 h-4" /> Mint Instance Key
        </Button>
      </div>

      <Card>
        <DataTable
          rows={keysQuery.data}
          rowKey={key => key.id}
          isLoading={keysQuery.isLoading}
          isError={keysQuery.isError}
          onRetry={() => keysQuery.refetch()}
          loadingLabel="Loading instance keys..."
          empty="No instance keys have been minted."
          emptyIcon={KeyRound}
          columns={[
            {
              key: 'label',
              header: 'Label',
              cellClassName: 'font-medium',
              cell: key => key.label,
            },
            {
              key: 'key',
              header: 'Key',
              cellClassName: 'font-mono text-xs text-muted-foreground',
              cell: key => <>{key.prefix}…</>,
            },
            {
              key: 'user',
              header: 'User',
              cellClassName: 'text-sm',
              cell: key => {
                const user = usersQuery.data?.find(candidate => candidate.id === key.user_id);
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
              cell: key => key.scopes?.join(', ') ?? 'Full authority',
            },
            {
              key: 'status',
              header: 'Status',
              cell: key => (
                <Badge variant={key.revoked ? 'outline' : 'success'}>
                  {key.revoked ? 'REVOKED' : 'ACTIVE'}
                </Badge>
              ),
            },
            {
              key: 'created',
              header: 'Created',
              cellClassName: 'text-muted-foreground text-sm',
              cell: key => formatDate(key.created_at),
            },
            {
              key: 'actions',
              header: 'Actions',
              headClassName: 'text-right',
              cellClassName: 'text-right',
              cell: key =>
                key.revoked ? null : (
                  <ConfirmButton
                    size="sm"
                    title={`Revoke "${key.label}"?`}
                    description="Services using this key will lose access immediately. This cannot be undone."
                    confirmLabel="Revoke key"
                    pending={revokeKey.isPending}
                    onConfirm={() => revokeKey.mutate({ keyId: key.id })}
                  >
                    Revoke
                  </ConfirmButton>
                ),
            },
          ]}
        />
      </Card>

      <FormDialog
        open={mintOpen}
        onOpenChange={setMintOpen}
        title="Mint an instance key"
        description="Use a clear label so you can identify this credential later. The secret is shown only once."
        schema={instanceKeySchema}
        defaultValues={{ label: '' }}
        onSubmit={async values => {
          const minted = await mintKey.mutateAsync({ data: values });
          setToken(minted.token);
        }}
        submitLabel="Mint key"
        pendingLabel="Minting..."
        pending={mintKey.isPending}
      >
        {form => (
          <FormField
            control={form.control}
            name="label"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Label</FormLabel>
                <FormControl>
                  <Input autoFocus placeholder="e.g. production-worker" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        )}
      </FormDialog>

      <KeyRevealDialog
        open={!!token}
        onOpenChange={open => !open && setToken(null)}
        token={token}
      />
    </div>
  );
}