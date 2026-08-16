import type { UseFormReturn } from 'react-hook-form';
import * as z from 'zod';
import { Permission, type Permission as PermissionName } from '@workspace/api-client-react';
import { Input } from '@/components/ui/elements';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';

const knownPermissions = new Set<string>(Object.values(Permission));

export function parsePermissions(value: string): PermissionName[] {
  return value
    .split(',')
    .map((permission) => permission.trim())
    .filter((permission): permission is PermissionName => knownPermissions.has(permission));
}

export const accessKeyFormSchema = z.object({
  label: z.string().min(1, 'Label is required').max(80, 'Label must be 80 characters or fewer'),
  permissions: z
    .string()
    .min(1, 'At least one permission is required')
    .refine((value) => {
      const submitted = value
        .split(',')
        .map((permission) => permission.trim())
        .filter(Boolean);
      return submitted.length > 0 && submitted.every((permission) => knownPermissions.has(permission));
    }, 'Use comma-separated permission names from the authority catalog'),
});

export type AccessKeyFormValues = z.infer<typeof accessKeyFormSchema>;

export function AccessKeyFormFields({ form }: { form: UseFormReturn<AccessKeyFormValues> }) {
  return (
    <>
      <FormField
        control={form.control}
        name="label"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Label</FormLabel>
            <FormControl>
              <Input placeholder="e.g. ci-deploy" {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="permissions"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Permissions</FormLabel>
            <FormControl>
              <Input placeholder="e.g. workspaces.read, bundles.publish" {...field} />
            </FormControl>
            <p className="text-xs text-muted-foreground">Comma-separated permission names. The key can only narrow the principal’s current role.</p>
            <FormMessage />
          </FormItem>
        )}
      />
    </>
  );
}
