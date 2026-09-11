import { useState } from 'react';
import type { ManagementKeyOut } from '@workspace/api-client-react';
import { Pencil } from 'lucide-react';
import { Button } from '@/components/ui/elements';
import { FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { PermissionChecklist, managementKeyFormSchema } from '@/components/shared/management-key-form';
import { PermissionsCell } from '@/components/shared/permissions-cell';
import { FormDialog } from '@/components/shared/form-dialog';
import { ErrorState } from '@/components/shared/states';
import { useScopedAuthorization } from '@/features/permissions/hooks';
import { useUpdateManagementKeyPermissionsMutation } from '@/features/keys/hooks';
import { managementKeyAccess } from '@/features/keys/policy';

const permissionsSchema = managementKeyFormSchema.pick({ permissions: true });

function ManagementKeyPermissionsDialog({ apiKey, onClose }: { apiKey: ManagementKeyOut; onClose: () => void }) {
  const authorization = useScopedAuthorization(
    apiKey.scope.workspace_id && apiKey.scope.org_id
      ? { level: 'workspace', orgId: apiKey.scope.org_id, workspaceRef: apiKey.scope.workspace_id }
      : apiKey.scope.org_id
        ? { level: 'org', orgId: apiKey.scope.org_id }
        : { level: 'instance' },
  );
  const update = useUpdateManagementKeyPermissionsMutation();
  const canEdit = authorization.can(managementKeyAccess.instance.updatePermissions);
  const availablePermissions = [...new Set([...authorization.permissions, ...apiKey.permissions])];

  return (
    <FormDialog
      open
      onOpenChange={(open) => !open && onClose()}
      title="Edit management key permissions"
      description={`Update permissions for ${apiKey.label}. The token stays the same. Changes apply to subsequent requests and limit delegated keys.`}
      schema={permissionsSchema}
      defaultValues={{ permissions: apiKey.permissions }}
      onSubmit={(data) => update.mutateAsync({ keyId: apiKey.id, data })}
      submitLabel="Save permissions"
      pendingLabel="Saving..."
      pending={update.isPending}
      submitDisabled={authorization.isFetching || authorization.isError || !canEdit}
    >
      {(form) => (
        <>
          {update.isError && <ErrorState error={update.error} resource="management key permissions" />}
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
                  grantablePermissions={authorization.permissions}
                  canIssue={canEdit}
                  permissionsLoading={authorization.isFetching}
                  permissionsError={authorization.error}
                  onPermissionsRetry={() => authorization.refetch()}
                />
                <FormMessage />
              </FormItem>
            )}
          />
        </>
      )}
    </FormDialog>
  );
}

export function ManagementKeyPermissionsCell({ apiKey, canEdit }: { apiKey: ManagementKeyOut; canEdit: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="inline-flex items-center gap-2 whitespace-nowrap">
      <PermissionsCell compact permissions={apiKey.permissions} />
      {canEdit && apiKey.status === 'active' && (
        <Button variant="ghost" size="icon" className="shrink-0" aria-label={`Edit permissions for ${apiKey.label}`} onClick={() => setOpen(true)}>
          <Pencil className="size-3.5" />
        </Button>
      )}
      {open && <ManagementKeyPermissionsDialog apiKey={apiKey} onClose={() => setOpen(false)} />}
    </div>
  );
}
