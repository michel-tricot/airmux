import { type AriaAttributes, type ReactNode } from 'react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/elements';
import { LoadingState, ErrorState, EmptyState } from '@/components/shared/states';

export interface Column<T> {
  key: string;
  header: ReactNode;
  sortDirection?: AriaAttributes['aria-sort'];
  headClassName?: string;
  cellClassName?: string;
  cell: (row: T) => ReactNode;
}

interface DataTableProps<T> {
  columns: Array<Column<T>>;
  rows: T[] | undefined;
  rowKey: (row: T) => string;
  rowClassName?: string;
  isLoading?: boolean;
  isError?: boolean;
  error?: unknown;
  resource?: string;
  onRetry?: () => void;
  loadingLabel?: string;
  errorMessage?: string;
  empty: ReactNode;
  emptyIcon?: React.ComponentType<{ className?: string }>;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  rowClassName,
  isLoading,
  isError,
  error,
  resource,
  onRetry,
  loadingLabel,
  errorMessage,
  empty,
  emptyIcon,
}: DataTableProps<T>) {
  if (isLoading) return <LoadingState label={loadingLabel} />;
  if (isError) return <ErrorState error={error} resource={resource} message={errorMessage} onRetry={onRetry} />;
  if (!rows || rows.length === 0) return <EmptyState icon={emptyIcon}>{empty}</EmptyState>;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          {columns.map((col) => (
            <TableHead key={col.key} className={col.headClassName} aria-sort={col.sortDirection}>
              {col.header}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={rowKey(row)} className={rowClassName}>
            {columns.map((col) => (
              <TableCell key={col.key} className={col.cellClassName}>
                {col.cell(row)}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
