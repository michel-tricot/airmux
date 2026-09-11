import { Card, Badge, ConfirmButton } from '@/components/ui/elements';
import { cn } from '@/lib/utils';
import { Ban } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { DataTable, type Column } from '@/components/shared/data-table';

interface KeyRow {
  id: string;
  label: string;
  prefix: string;
  revoked?: boolean;
  revoked_at?: string | null;
  status?: string;
  created_at: string;
}

export interface KeysTableProps<T extends KeyRow> {
  resource: string;
  keys: T[] | undefined;
  isLoading?: boolean;
  isError?: boolean;
  error?: unknown;
  onRetry?: () => void;
  emptyText: string;
  extraColumns?: Array<Column<T>>;
  revokeDescription?: string;
  onRevoke?: (key: T) => Promise<unknown>;
  revokePending?: boolean;
}

export function KeysTable<T extends KeyRow>({
  resource,
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
}: KeysTableProps<T>) {
  const statusOf = (key: T) => key.status ?? (key.revoked === true || key.revoked_at != null ? 'revoked' : 'active');
  const isRevoked = (key: T) => statusOf(key) === 'revoked';
  const columns: Array<Column<T>> = [
    {
      key: 'label',
      header: 'Label',
      cellClassName: 'font-medium',
      cell: (key) => (
        <span className="block truncate" title={key.label}>
          {key.label}
        </span>
      ),
    },
    {
      key: 'prefix',
      header: 'Key',
      cellClassName: 'font-mono text-xs text-muted-foreground',
      cell: (key) => (
        <span className="block truncate" title={key.prefix}>
          {key.prefix}…
        </span>
      ),
    },
    ...extraColumns,
    {
      key: 'status',
      header: 'Status',
      headClassName: 'w-24',
      cell: (key) => {
        const status = statusOf(key);
        return <Badge variant={status === 'active' ? 'success' : 'outline'}>{status.toUpperCase()}</Badge>;
      },
    },
    {
      key: 'created',
      header: 'Created',
      headClassName: 'w-44',
      cellClassName: 'text-muted-foreground text-sm',
      cell: (key) => (
        <span className="block truncate" title={formatDate(key.created_at)}>
          {formatDate(key.created_at)}
        </span>
      ),
    },
  ];
  if (onRevoke) {
    columns.push({
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      headClassName: 'w-12 text-right',
      cellClassName: 'text-right',
      cell: (key) =>
        isRevoked(key) ? null : (
          <ConfirmButton
            size="icon"
            aria-label={`Revoke ${key.label}`}
            title={`Revoke "${key.label}"?`}
            description={revokeDescription ?? 'This key will stop working immediately.'}
            confirmLabel="Revoke key"
            pending={revokePending}
            onConfirm={() => onRevoke(key)}
          >
            <Ban className="size-4" />
          </ConfirmButton>
        ),
    });
  }

  return (
    <Card>
      <DataTable
        tableClassName="table-fixed"
        columns={columns.map((column) => ({ ...column, cellClassName: cn(column.cellClassName, 'whitespace-nowrap', 'overflow-hidden') }))}
        rows={keys}
        rowKey={(key) => key.id}
        isLoading={isLoading}
        isError={isError}
        error={error}
        resource={resource}
        onRetry={onRetry}
        empty={emptyText}
      />
    </Card>
  );
}
