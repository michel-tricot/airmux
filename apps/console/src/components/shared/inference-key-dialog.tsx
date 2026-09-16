import * as z from 'zod';
import { Dropdown, Input } from '@/components/ui/elements';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { FormDialog } from '@/components/shared/form-dialog';
import { useCreateInferenceKeyMutation, useInferenceKeyOwners } from '@/features/keys/hooks';
import { ErrorState } from '@/components/shared/states';

const inferenceKeySchema = z.object({
  label: z.string().min(1, 'Label is required'),
  userId: z.string().min(1, 'Owner is required'),
});

export function InferenceKeyDialog({
  orgId,
  workspaceRef,
  open,
  onOpenChange,
  onCreated,
  currentUser,
}: {
  orgId: string;
  workspaceRef: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (token: string) => void;
  currentUser: { user_id: string; name: string; email: string };
}) {
  const createKey = useCreateInferenceKeyMutation(orgId, workspaceRef);
  const owners = useInferenceKeyOwners(orgId, workspaceRef);
  const ownerOptions = owners.data?.map((owner) => ({
    value: owner.user_id,
    label: owner.service_account ? `${owner.name} (service account)` : `${owner.name} (you)`,
  })) ?? [{ value: currentUser.user_id, label: `${currentUser.name} (you)` }];
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Generate Inference Key"
      description="Choose the principal this credential represents. Use a service account for applications and production workloads."
      schema={inferenceKeySchema}
      defaultValues={{ label: '', userId: currentUser.user_id }}
      onSubmit={async (values) => {
        const key = await createKey.mutateAsync({ orgId, workspaceRef, data: { label: values.label, user_id: values.userId } });
        onCreated(key.token);
      }}
      submitLabel="Generate"
      pending={createKey.isPending}
    >
      {(form) => (
        <>
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
          <FormField
            control={form.control}
            name="userId"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Owner</FormLabel>
                <FormControl>
                  <Dropdown aria-label="Owner" value={field.value} onValueChange={field.onChange} options={ownerOptions} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          {owners.isError && (
            <ErrorState
              error={owners.error}
              message="Service-account owners are unavailable. You can still create a key for yourself."
              onRetry={() => owners.refetch()}
              className="p-0"
            />
          )}
        </>
      )}
    </FormDialog>
  );
}
