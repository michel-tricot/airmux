import { useState } from 'react';
import { Check, Plus } from 'lucide-react';
import { SearchField } from '@/components/shared/search-field';
import type { UseFormReturn } from 'react-hook-form';
import * as z from 'zod';
import { Permission, type ManagementKeyGrantIn, type Permission as PermissionName } from '@workspace/api-client-react';
import { Button, Dropdown, Input } from '@/components/ui/elements';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { cn } from '@/lib/utils';
import { ErrorState } from '@/components/shared/states';
import { groupPermissions } from '@/components/shared/permission-groups';

export const managementKeyFormSchema = z.object({
  expiry: z.enum(['7', '30', '90', '365', 'never']),
  label: z.string().min(1, 'Label is required').max(80, 'Label must be 80 characters or fewer'),
  permissions: z.array(z.nativeEnum(Permission)).min(1, 'Select at least one permission'),
});

export type ManagementKeyFormValues = z.infer<typeof managementKeyFormSchema>;

export function managementKeyPayload(values: ManagementKeyFormValues, now = new Date()): ManagementKeyGrantIn {
  return {
    label: values.label,
    permissions: values.permissions,
    expires_at: values.expiry === 'never' ? undefined : new Date(now.getTime() + Number(values.expiry) * 86400000).toISOString(),
  };
}

export const managementKeyExpiryOptions = [
  { value: '7', label: '7 days' },
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: '1 year' },
  { value: 'never', label: 'Never' },
];

const resourceLabels: Record<string, string> = {
  'management-keys': 'Management keys',
  'inference-keys': 'Inference keys',
  'provider-credentials': 'Provider credentials',
  'data-planes': 'Data planes',
  organizations: 'Organizations',
  principals: 'Users and service accounts',
  members: 'Members',
  workspaces: 'Workspaces',
  catalog: 'Model catalog',
  policies: 'Policies',
  playground: 'Playground',
  bundles: 'Configuration bundles',
  usage: 'Usage',
  audit: 'Activity log',
};

const actionLabels: Record<string, string> = {
  read: 'Read',
  create: 'Create',
  update: 'Edit',
  delete: 'Delete',
  manage: 'Manage',
  execute: 'Run',
  publish: 'Publish',
  ingest: 'Ingest',
  heartbeat: 'Heartbeat',
  issue: 'Generate',
  revoke: 'Revoke',
};

function actionLabel(permission: PermissionName) {
  const action = permission.slice(permission.indexOf('.') + 1);
  return actionLabels[action] ?? action;
}

export function PermissionChecklist({
  value,
  onChange,
  availablePermissions,
  grantablePermissions = availablePermissions,
  canIssue,
  permissionsLoading,
  permissionsError,
  onPermissionsRetry,
}: {
  value: PermissionName[];
  onChange: (value: PermissionName[]) => void;
  availablePermissions: readonly PermissionName[];
  grantablePermissions?: readonly PermissionName[];
  canIssue: boolean;
  permissionsLoading?: boolean;
  permissionsError?: unknown;
  onPermissionsRetry?: () => void;
}) {
  const [search, setSearch] = useState('');
  const query = search.trim().toLowerCase();
  const groups = groupPermissions(availablePermissions)
    .map(([resource, permissions]) => ({
      resource,
      label: resourceLabels[resource] ?? resource,
      permissions: permissions.filter((permission) =>
        `${resourceLabels[resource] ?? resource} ${permission} ${actionLabel(permission)}`.toLowerCase().includes(query),
      ),
    }))
    .filter((group) => group.permissions.length > 0);
  const needsRemoval = value.some((permission) => !grantablePermissions.includes(permission));

  if (permissionsLoading) return <p className="text-xs text-muted-foreground">Loading your permissions...</p>;
  if (permissionsError) {
    return (
      <ErrorState error={permissionsError} resource="permissions" onRetry={onPermissionsRetry} className="rounded-md border border-border p-3" />
    );
  }
  if (!canIssue) return <p className="text-xs text-muted-foreground">You do not have permission to issue management keys at this scope.</p>;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <SearchField
          value={search}
          onValueChange={setSearch}
          label="Search permissions"
          placeholder="Find a resource or action..."
          className="max-w-none"
        />
        <span aria-live="polite" className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {value.length} selected
        </span>
      </div>
      <div className="h-64 max-h-[40vh] overflow-y-auto overscroll-contain rounded-md border border-border px-2">
        {groups.length === 0 && (
          <p className="rounded-lg border border-dashed border-border py-8 text-center text-sm text-muted-foreground">No matching permissions</p>
        )}
        {groups.map(({ resource, label, permissions }) => (
          <fieldset
            key={resource}
            aria-label={label}
            className="flex min-w-0 flex-col gap-2 border-b border-border py-2 last:border-0 sm:flex-row sm:items-center sm:gap-3"
          >
            <div className="flex shrink-0 items-center justify-between gap-2 sm:w-36">
              <span className="text-xs font-medium">{label}</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {permissions.map((permission) => {
                const checked = value.includes(permission);
                return (
                  <Button
                    key={permission}
                    role="checkbox"
                    aria-label={permission}
                    aria-checked={checked}
                    title={permission}
                    variant="outline"
                    size="sm"
                    disabled={!checked && !grantablePermissions.includes(permission)}
                    onClick={() => onChange(checked ? value.filter((item) => item !== permission) : [...value, permission])}
                    className={cn(
                      'h-7 gap-1 rounded px-2 font-sans text-[11px] font-medium normal-case tracking-normal transition-colors',
                      checked
                        ? 'border-primary/40 bg-primary/15 text-primary hover:bg-primary/20'
                        : 'border-border bg-background text-muted-foreground hover:text-foreground',
                    )}
                  >
                    {checked ? <Check className="size-3.5" aria-hidden="true" /> : <Plus className="size-3.5 opacity-50" aria-hidden="true" />}
                    {actionLabel(permission)}
                  </Button>
                );
              })}
            </div>
          </fieldset>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        {needsRemoval
          ? 'Remove permissions you no longer hold before saving.'
          : 'Select the access this key needs. Hover over an action to see its permission name.'}
      </p>
    </div>
  );
}

export function ManagementKeyFormFields({
  form,
  availablePermissions,
  canIssue,
  permissionsLoading,
  permissionsError,
  onPermissionsRetry,
}: {
  form: UseFormReturn<ManagementKeyFormValues>;
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
        name="expiry"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Expires in</FormLabel>
            <FormControl>
              <Dropdown value={field.value} onValueChange={field.onChange} options={managementKeyExpiryOptions} />
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
