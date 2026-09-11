import * as z from 'zod';
import { Input } from '@/components/ui/elements';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { FormDialog } from '@/components/shared/form-dialog';
import { useCreateInferenceKeyMutation } from '@/features/keys/hooks';

const keyLabelSchema = z.object({ label: z.string().min(1, 'Label is required') });

export function InferenceKeyDialog({
  orgId,
  workspaceRef,
  open,
  onOpenChange,
  onCreated,
}: {
  orgId: string;
  workspaceRef: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (token: string) => void;
}) {
  const createKey = useCreateInferenceKeyMutation(orgId, workspaceRef);
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Generate API Key"
      description="Keys let applications send requests to the models available to this workspace."
      schema={keyLabelSchema}
      defaultValues={{ label: '' }}
      onSubmit={async (values) => {
        const minted = await createKey.mutateAsync({ orgId, workspaceRef, data: values });
        onCreated(minted.token);
      }}
      submitLabel="Generate"
      pending={createKey.isPending}
    >
      {(form) => (
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
  );
}
