import * as z from 'zod';
import type { OrgCreate, OrgOut } from '@workspace/api-client-react';
import { FormDialog } from '@/components/shared/form-dialog';
import { Input } from '@/components/ui/elements';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';

const createOrgSchema = z.object({ name: z.string().trim().min(1, 'Name is required') });

export function CreateOrganizationDialog({
  open,
  onOpenChange,
  onSubmit,
  pending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: OrgCreate) => Promise<OrgOut>;
  pending: boolean;
}) {
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Create Organization"
      description="Set up a new organization."
      schema={createOrgSchema}
      defaultValues={{ name: '' }}
      onSubmit={onSubmit}
      submitLabel="Create Organization"
      pendingLabel="Creating..."
      pending={pending}
    >
      {(form) => (
        <FormField
          control={form.control}
          name="name"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Name</FormLabel>
              <FormControl>
                <Input placeholder="Acme Corp" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      )}
    </FormDialog>
  );
}
