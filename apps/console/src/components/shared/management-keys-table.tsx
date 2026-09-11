import { AccountIdentity } from '@/components/shared/account-display';
import type { ManagementKeyOut } from '@workspace/api-client-react';
import { ManagementKeyScope } from '@/components/shared/management-key-scope';
import { KeysTable, type KeysTableProps } from '@/components/shared/keys-table';
import { ManagementKeyPermissionsCell } from '@/components/shared/management-key-permissions-cell';

export function ManagementKeysTable({
  canEditPermissions,
  extraColumns = [],
  owners,
  ownerHref,
  ...props
}: KeysTableProps<ManagementKeyOut> & {
  canEditPermissions: boolean;
  owners: ReadonlyMap<string, { name: string }>;
  ownerHref?: (userId: string) => string;
}) {
  return (
    <KeysTable
      {...props}
      extraColumns={[
        ...extraColumns,
        {
          key: 'owner',
          header: 'Owner',
          cell: (key) => {
            const owner = owners.get(key.user_id);
            return owner ? (
              <AccountIdentity name={owner.name} href={ownerHref?.(key.user_id)} />
            ) : (
              <span className="block truncate font-mono text-xs text-muted-foreground" title={key.user_id}>
                {key.user_id}
              </span>
            );
          },
        },
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
