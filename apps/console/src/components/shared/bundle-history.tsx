import type { BundleOut } from '@workspace/api-client-react';
import { Card } from '@/components/ui/elements';
import { DataTable } from '@/components/shared/data-table';
import { formatDate } from '@/lib/format';

export function BundleHistory({
  bundles,
  isLoading,
  isError,
  error,
  onRetry,
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
}: {
  bundles: BundleOut[] | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  onRetry: () => void;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => void;
}) {
  return (
    <Card>
      <DataTable
        rows={bundles?.toSorted((first, second) => second.version - first.version)}
        rowKey={(bundle) => bundle.id}
        isLoading={isLoading}
        isError={isError}
        error={error}
        onRetry={onRetry}
        hasNextPage={hasNextPage}
        isFetchingNextPage={isFetchingNextPage}
        onLoadMore={onLoadMore}
        resource="configuration bundles"
        empty="No configuration bundles have been generated yet."
        columns={[
          { key: 'version', header: 'Version', cellClassName: 'font-mono font-medium', cell: (bundle) => `v${bundle.version}` },
          { key: 'id', header: 'Bundle ID', cellClassName: 'font-mono text-xs text-muted-foreground', cell: (bundle) => bundle.id },
          { key: 'generated', header: 'Generated', cellClassName: 'text-muted-foreground text-sm', cell: (bundle) => formatDate(bundle.issued_at) },
        ]}
      />
    </Card>
  );
}
