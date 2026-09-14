import { useState } from 'react';
import type { ManagementKeyIn, Permission } from '@workspace/api-client-react';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { FormDialog } from '@/components/shared/form-dialog';
import { ManagementKeyFormFields, managementKeyFormSchema, managementKeyPayload } from '@/components/shared/management-key-form';

export function ManagementKeyDialog({
  open,
  onOpenChange,
  title,
  description,
  availablePermissions,
  canIssue,
  permissionsLoading,
  permissionsError,
  onPermissionsRetry,
  pending,
  submitDisabled,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  availablePermissions: readonly Permission[];
  canIssue: boolean;
  permissionsLoading?: boolean;
  permissionsError?: unknown;
  onPermissionsRetry?: () => void;
  pending: boolean;
  submitDisabled?: boolean;
  onSubmit: (data: ManagementKeyIn) => Promise<string>;
}) {
  const [token, setToken] = useState<string | null>(null);

  return (
    <>
      <FormDialog
        open={open}
        onOpenChange={onOpenChange}
        title={title}
        description={description}
        schema={managementKeyFormSchema}
        defaultValues={{ label: '', permissions: [], expiry: 'never' }}
        onSubmit={async (values) => setToken(await onSubmit(managementKeyPayload(values)))}
        submitLabel="Generate"
        pendingLabel="Generating..."
        pending={pending}
        submitDisabled={submitDisabled}
      >
        {(form) => (
          <ManagementKeyFormFields
            form={form}
            availablePermissions={availablePermissions}
            canIssue={canIssue}
            permissionsLoading={permissionsLoading}
            permissionsError={permissionsError}
            onPermissionsRetry={onPermissionsRetry}
          />
        )}
      </FormDialog>
      <KeyRevealDialog open={token !== null} onOpenChange={(nextOpen) => !nextOpen && setToken(null)} token={token} />
    </>
  );
}
