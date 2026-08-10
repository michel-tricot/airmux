import { Card, Badge, ConfirmButton } from '@/components/ui/elements';
import { Ban } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { DataTable, type Column } from '@/components/shared/data-table';

export interface ApiKeyRow {
  id: string;
  label: string;
  prefix: string;
  revoked: boolean;
  created_at: string;
}

interface ApiKeysTableProps<T extends ApiKeyRow> {
  keys: T[] | undefined;
  isLoading?: boolean;
  isError?: boolean;
  onRetry?: () => void;
  emptyText: string;
  /** Extra columns rendered between the Key and Status columns (e.g. User, Permissions). */
  extraColumns?: Array<Column<T>>;
  revokeDescription: string;
  onRevoke: (key: T) => void;
  revokePending: boolean;
}

/**
 * API-key table shared by the management-key and inference-key views:
 * label/prefix/status/created columns and a confirm-to-revoke action.
 */
export function ApiKeysTable<T extends ApiKeyRow>({
  keys,
  isLoading,
  isError,
  onRetry,
  emptyText,
  extraColumns = [],
  revokeDescription,
  onRevoke,
  revokePending,
}: ApiKeysTableProps<T>) {
  const columns: Array<Column<T>> = [
    { key: 'label', header: 'Label', cellClassName: 'font-medium', cell: key => key.label },
    {
      key: 'prefix',
      header: 'Key',
      cellClassName: 'font-mono text-xs text-muted-foreground',
      cell: key => <>{key.prefix}…</>,
    },
    ...extraColumns,
    {
      key: 'status',
      header: 'Status',
      cell: key => <Badge variant={key.revoked ? 'outline' : 'success'}>{key.revoked ? 'REVOKED' : 'ACTIVE'}</Badge>,
    },
    {
      key: 'created',
      header: 'Created',
      cellClassName: 'text-muted-foreground text-sm',
      cell: key => formatDate(key.created_at),
    },
    {
      key: 'actions',
      header: 'Actions',
      headClassName: 'text-right',
      cellClassName: 'text-right',
      cell: key =>
        key.revoked ? null : (
          <ConfirmButton size="sm"
            title={`Revoke "${key.label}"?`}
            description={revokeDescription}
            confirmLabel="Revoke key"
            pending={revokePending}
            onConfirm={() => onRevoke(key)}>
            <Ban className="w-4 h-4 mr-1" /> Revoke
          </ConfirmButton>
        ),
    },
  ];

  return (
    <Card>
      <DataTable columns={columns} rows={keys} rowKey={key => key.id} isLoading={isLoading}
        isError={isError} onRetry={onRetry} empty={emptyText} />
    </Card>
  );
}
