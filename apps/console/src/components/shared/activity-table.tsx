import type { ReactNode } from 'react';
import type { ActivityOut } from '@workspace/api-client-react';
import { Badge } from '@/components/ui/elements';
import { DataTable } from '@/components/shared/data-table';
import { formatDate } from '@/lib/format';

interface ActivityTableProps {
  entries: ActivityOut[] | undefined;
  isLoading?: boolean;
  isError?: boolean;
  error?: unknown;
  onRetry?: () => void;
  emptyText: string;
  recordLabel?: (entry: ActivityOut) => string | null;
  renderActor: (entry: ActivityOut) => ReactNode;
}

export function ActivityTable({ entries, isLoading, isError, error, onRetry, emptyText, recordLabel, renderActor }: ActivityTableProps) {
  return (
    <DataTable
      rows={entries}
      rowKey={(entry) => (entry.id === null ? `${entry.record_id}-${entry.occurred_at}` : String(entry.id))}
      isLoading={isLoading}
      isError={isError}
      error={error}
      resource="activity"
      onRetry={onRetry}
      loadingLabel="Loading activity..."
      empty={emptyText}
      columns={[
        {
          key: 'action',
          header: 'Action',
          headClassName: 'w-[120px]',
          cell: (entry) => (
            <Badge variant={entry.action === 'delete' ? 'destructive' : entry.action === 'create' ? 'success' : 'secondary'} className="font-mono">
              {entry.action}
            </Badge>
          ),
        },
        {
          key: 'resource',
          header: 'Resource',
          cellClassName: 'font-medium',
          cell: (entry) => {
            const label = recordLabel?.(entry);
            return (
              <>
                {entry.table_name}
                {label && <span className="ml-2 text-muted-foreground">“{label}”</span>}
                <div className="font-mono text-xs text-muted-foreground">{entry.record_id}</div>
              </>
            );
          },
        },
        { key: 'actor', header: 'Actor', cellClassName: 'text-sm text-muted-foreground', cell: renderActor },
        {
          key: 'when',
          header: 'When',
          headClassName: 'text-right',
          cellClassName: 'text-right text-sm text-muted-foreground',
          cell: (entry) => formatDate(entry.occurred_at),
        },
      ]}
    />
  );
}
