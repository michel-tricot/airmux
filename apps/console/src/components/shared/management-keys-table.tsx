import type { ManagementKeyOut } from '@workspace/api-client-react';
import { Badge } from '@/components/ui/elements';
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
        { key: 'scope', header: 'Scope', headClassName: 'w-24', cell: (key) => <Badge variant="secondary">{key.scope.level}</Badge> },
        {
          key: 'permissions',
          header: 'Permissions',
          headClassName: 'w-40',
          cell: (key) => <ManagementKeyPermissionsCell apiKey={key} canEdit={canEditPermissions} />,
        },
      ]}
    />
  );
}
