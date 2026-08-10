import { type ReactNode } from 'react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/elements';
import { LoadingState, ErrorState, EmptyState } from '@/components/shared/states';

export interface Column<T> {
  key: string;
  header: ReactNode;
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
  onRetry?: () => void;
  loadingLabel?: string;
  errorMessage?: string;
  empty: ReactNode;
  emptyIcon?: React.ComponentType<{ className?: string }>;
}

/**
 * Entity table with the loading / error / empty states every list view shares.
 * Wrap it in a Card at the call site; columns own their cell rendering.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  rowClassName,
  isLoading,
  isError,
  onRetry,
  loadingLabel,
  errorMessage,
  empty,
  emptyIcon,
}: DataTableProps<T>) {
  if (isLoading) return <LoadingState label={loadingLabel} />;
  if (isError) return <ErrorState message={errorMessage} onRetry={onRetry} />;
  if (!rows || rows.length === 0) return <EmptyState icon={emptyIcon}>{empty}</EmptyState>;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          {columns.map(col => (
            <TableHead key={col.key} className={col.headClassName}>{col.header}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map(row => (
          <TableRow key={rowKey(row)} className={rowClassName}>
            {columns.map(col => (
              <TableCell key={col.key} className={col.cellClassName}>{col.cell(row)}</TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
