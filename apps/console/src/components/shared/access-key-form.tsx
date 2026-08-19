import type { UseFormReturn } from 'react-hook-form';
import * as z from 'zod';
import { Permission, type Permission as PermissionName } from '@workspace/api-client-react';
import { Input } from '@/components/ui/elements';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { cn } from '@/lib/utils';
import { ErrorState } from '@/components/shared/states';
import { groupPermissions } from '@/components/shared/permission-groups';

export const accessKeyFormSchema = z.object({
  label: z.string().min(1, 'Label is required').max(80, 'Label must be 80 characters or fewer'),
  permissions: z.array(z.nativeEnum(Permission)).min(1, 'Select at least one permission'),
});

export type AccessKeyFormValues = z.infer<typeof accessKeyFormSchema>;

export function PermissionChecklist({
  value,
  onChange,
  availablePermissions,
  canIssue,
  permissionsLoading,
  permissionsError,
  onPermissionsRetry,
}: {
  value: PermissionName[];
  onChange: (value: PermissionName[]) => void;
  availablePermissions: readonly PermissionName[];
  canIssue: boolean;
  permissionsLoading?: boolean;
  permissionsError?: unknown;
  onPermissionsRetry?: () => void;
}) {
  if (permissionsLoading) return <p className="text-xs text-muted-foreground">Loading your permissions...</p>;
  if (permissionsError) {
    return (
      <ErrorState error={permissionsError} resource="permissions" onRetry={onPermissionsRetry} className="rounded-md border border-border p-3" />
    );
  }
  if (!canIssue) return <p className="text-xs text-muted-foreground">You do not have permission to issue access keys at this scope.</p>;
  return (
    <>
      <div className="permission-scrollbar max-h-64 space-y-3 overflow-y-auto rounded-md border border-border bg-card/30 p-3">
        {groupPermissions(availablePermissions).map(([resource, permissions]) => (
          <div key={resource} className="space-y-1">
            <div className="font-mono text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{resource}</div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1">
              {permissions.map((permission) => {
                const checked = value.includes(permission);
                return (
                  <label
                    key={permission}
                    className={cn(
                      'flex cursor-pointer items-center gap-2 rounded-sm px-1.5 py-1 text-xs',
                      checked ? 'text-foreground' : 'text-muted-foreground hover:text-foreground',
                    )}
                  >
                    <input
                      type="checkbox"
                      className="size-3.5 accent-primary"
                      checked={checked}
                      onChange={(event) => onChange(event.target.checked ? [...value, permission] : value.filter((item) => item !== permission))}
                    />
                    <span className="font-mono">{permission}</span>
                  </label>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">Only permissions you currently hold are listed. The key can never exceed them.</p>
    </>
  );
}

export function AccessKeyFormFields({
  form,
  availablePermissions,
  canIssue,
  permissionsLoading,
  permissionsError,
  onPermissionsRetry,
}: {
  form: UseFormReturn<AccessKeyFormValues>;
  availablePermissions: readonly PermissionName[];
  canIssue: boolean;
  permissionsLoading?: boolean;
  permissionsError?: unknown;
  onPermissionsRetry?: () => void;
}) {
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
            <PermissionChecklist
              value={field.value}
              onChange={field.onChange}
              availablePermissions={availablePermissions}
              canIssue={canIssue}
              permissionsLoading={permissionsLoading}
              permissionsError={permissionsError}
              onPermissionsRetry={onPermissionsRetry}
            />
            <FormMessage />
          </FormItem>
        )}
      />
    </>
  );
}
