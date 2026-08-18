import { Card, Badge, ConfirmButton } from '@/components/ui/elements';
import { Ban } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { DataTable, type Column } from '@/components/shared/data-table';

interface ApiKeyRow {
  id: string;
  label: string;
  prefix: string;
  revoked?: boolean;
  revoked_at?: string | null;
  status?: string;
  created_at: string;
}

interface ApiKeysTableProps<T extends ApiKeyRow> {
  keys: T[] | undefined;
  isLoading?: boolean;
  isError?: boolean;
  error?: unknown;
  onRetry?: () => void;
  emptyText: string;
  extraColumns?: Array<Column<T>>;
  revokeDescription: string;
  onRevoke?: (key: T) => Promise<unknown>;
  revokePending?: boolean;
}

export function ApiKeysTable<T extends ApiKeyRow>({
  keys,
  isLoading,
  isError,
  error,
  onRetry,
  emptyText,
  extraColumns = [],
  revokeDescription,
  onRevoke,
  revokePending,
}: ApiKeysTableProps<T>) {
  const statusOf = (key: T) => key.status ?? (key.revoked === true || key.revoked_at != null ? 'revoked' : 'active');
  const isRevoked = (key: T) => statusOf(key) === 'revoked';
  const columns: Array<Column<T>> = [
    { key: 'label', header: 'Label', cellClassName: 'font-medium', cell: (key) => key.label },
    {
      key: 'prefix',
      header: 'Key',
      cellClassName: 'font-mono text-xs text-muted-foreground',
      cell: (key) => <>{key.prefix}…</>,
    },
    ...extraColumns,
    {
      key: 'status',
      header: 'Status',
      cell: (key) => {
        const status = statusOf(key);
        return <Badge variant={status === 'active' ? 'success' : 'outline'}>{status.toUpperCase()}</Badge>;
      },
    },
    {
      key: 'created',
      header: 'Created',
      cellClassName: 'text-muted-foreground text-sm',
      cell: (key) => formatDate(key.created_at),
    },
  ];
  if (onRevoke) {
    columns.push({
      key: 'actions',
      header: 'Actions',
      headClassName: 'text-right',
      cellClassName: 'text-right',
      cell: (key) =>
        isRevoked(key) ? null : (
          <ConfirmButton
            size="sm"
            title={`Revoke "${key.label}"?`}
            description={revokeDescription}
            confirmLabel="Revoke key"
            pending={revokePending}
            onConfirm={() => onRevoke(key)}
          >
            <Ban className="w-4 h-4 mr-1" /> Revoke
          </ConfirmButton>
        ),
    });
  }

  return (
    <Card>
      <DataTable
        columns={columns}
        rows={keys}
        rowKey={(key) => key.id}
        isLoading={isLoading}
        isError={isError}
        error={error}
        resource="API keys"
        onRetry={onRetry}
        empty={emptyText}
      />
    </Card>
  );
}
