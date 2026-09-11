import type { ManagementKeyOut } from '@workspace/api-client-react';
import { ManagementKeyScope } from '@/components/shared/management-key-scope';
import { KeysTable, type KeysTableProps } from '@/components/shared/keys-table';
import { ManagementKeyPermissionsCell } from '@/components/shared/management-key-permissions-cell';

export function ManagementKeysTable({
  canEditPermissions,
  extraColumns = [],
  ...props
}: KeysTableProps<ManagementKeyOut> & { canEditPermissions: boolean }) {
  return (
    <KeysTable
      {...props}
      extraColumns={[
        ...extraColumns,
        { key: 'scope', header: 'Scope', headClassName: 'w-24', cell: (key) => <ManagementKeyScope scope={key.scope} /> },
        {
          key: 'permissions',
          header: 'Permissions',
          cell: (key) => <ManagementKeyPermissionsCell apiKey={key} canEdit={canEditPermissions} />,
        },
      ]}
    />
  );
}
