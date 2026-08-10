import { useState } from 'react';
import * as z from 'zod';
import { useParams } from 'wouter';
import { useSession } from '@/lib/session';
import { useInferenceKeys, useCreateInferenceKeyMutation, useRevokeInferenceKeyMutation } from '@/features/keys/hooks';
import { Button, Input } from '@/components/ui/elements';
import { Plus } from 'lucide-react';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { FormDialog } from '@/components/shared/form-dialog';
import { ApiKeysTable } from '@/components/shared/api-keys-table';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';

const keyLabelSchema = z.object({ label: z.string().min(1, 'Label is required') });

export default function WorkspaceApiKeys() {
  const { workspaceRef } = useParams();
  const { orgId } = useSession();

  const keysQuery = useInferenceKeys(orgId!, workspaceRef!);

  const [keyOpen, setKeyOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);

  const createKey = useCreateInferenceKeyMutation(orgId!, workspaceRef!);
  const revokeKey = useRevokeInferenceKeyMutation(orgId!, workspaceRef!);

  return (
    <div className="flex-1 p-8 max-w-6xl mx-auto w-full space-y-6 animate-in fade-in duration-300">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">API Keys</h1>
          <p className="text-muted-foreground mt-1 text-sm">Keys let applications send requests to the models available to this workspace.</p>
        </div>
        <Button onClick={() => setKeyOpen(true)}><Plus className="w-4 h-4 mr-1" /> Generate Key</Button>
      </div>

      <ApiKeysTable
        keys={keysQuery.data}
        isLoading={keysQuery.isLoading}
        isError={keysQuery.isError}
        onRetry={() => keysQuery.refetch()}
        emptyText="No inference keys generated."
        revokeDescription="Requests using this inference key will stop working immediately. This cannot be undone."
        onRevoke={key => revokeKey.mutate({ workspaceRef: workspaceRef!, keyId: key.id })}
        revokePending={revokeKey.isPending}
      />

      <FormDialog
        open={keyOpen}
        onOpenChange={setKeyOpen}
        title="Generate Inference Key"
        description="Keys let applications send requests to the models available to this workspace."
        schema={keyLabelSchema}
        defaultValues={{ label: '' }}
        onSubmit={async values => {
          const minted = await createKey.mutateAsync({ workspaceRef: workspaceRef!, data: values });
          setToken(minted.token);
        }}
        submitLabel="Generate"
        pending={createKey.isPending}>
        {form => (
          <FormField
            control={form.control}
            name="label"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Label</FormLabel>
                <FormControl>
                  <Input placeholder="e.g. chatbot-prod" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        )}
      </FormDialog>

      <KeyRevealDialog open={!!token} onOpenChange={(v) => !v && setToken(null)} token={token} />
    </div>
  );
}
