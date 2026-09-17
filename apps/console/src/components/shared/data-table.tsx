import { Fragment, type AriaAttributes, type ReactNode } from 'react';
import { Button, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/elements';
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
  tableClassName?: string;
  headerGroups?: Array<{
    key: string;
    label: ReactNode;
    colSpan: number;
    className?: string;
  }>;
  rows: T[] | undefined;
  rowKey: (row: T) => string;
  rowClassName?: string;
  renderRow?: (row: T, cells: ReactNode[]) => ReactNode;
  clipOverflow?: boolean;
  isLoading?: boolean;
  isError?: boolean;
  error?: unknown;
  resource?: string;
  onRetry?: () => void;
  loadingLabel?: string;
  errorMessage?: string;
  empty: ReactNode;
  emptyIcon?: React.ComponentType<{ className?: string }>;
  hasNextPage?: boolean;
  isFetchingNextPage?: boolean;
  onLoadMore?: () => void;
}

export function DataTable<T>({
  columns,
  tableClassName,
  headerGroups,
  rows,
  rowKey,
  rowClassName,
  renderRow,
  clipOverflow,
  isLoading,
  isError,
  error,
  resource,
  onRetry,
  loadingLabel,
  errorMessage,
  empty,
  emptyIcon,
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
}: DataTableProps<T>) {
  if (isLoading) return <LoadingState label={loadingLabel} />;
  if (isError) return <ErrorState error={error} resource={resource} message={errorMessage} onRetry={onRetry} />;
  if (!rows || rows.length === 0) return <EmptyState icon={emptyIcon}>{empty}</EmptyState>;

  return (
    <div className="space-y-3">
      <Table className={tableClassName} clipOverflow={clipOverflow}>
        <TableHeader>
          {headerGroups && (
            <TableRow className="bg-muted/20 hover:bg-muted/20">
              {headerGroups.map((group) => (
                <TableHead key={group.key} scope="colgroup" colSpan={group.colSpan} className={group.className}>
                  {group.label}
                </TableHead>
              ))}
            </TableRow>
          )}
          <TableRow>
            {columns.map((col) => (
              <TableHead key={col.key} className={col.headClassName} aria-sort={col.sortDirection}>
                {col.header}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const cells = columns.map((col) => (
              <TableCell key={col.key} className={col.cellClassName}>
                {col.cell(row)}
              </TableCell>
            ));
            return <Fragment key={rowKey(row)}>{renderRow ? renderRow(row, cells) : <TableRow className={rowClassName}>{cells}</TableRow>}</Fragment>;
          })}
        </TableBody>
      </Table>
      {hasNextPage && onLoadMore && (
        <div className="flex justify-center">
          <Button variant="outline" size="sm" disabled={isFetchingNextPage} onClick={onLoadMore}>
            {isFetchingNextPage ? 'Loading…' : 'Load more'}
          </Button>
        </div>
      )}
    </div>
  );
}
