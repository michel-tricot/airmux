import type { ReactNode } from 'react';
import type { ProviderCredentialOut } from '@workspace/api-client-react';
import { KeyRound } from 'lucide-react';
import { DataTable, type Column } from '@/components/shared/data-table';
import { Badge, Card } from '@/components/ui/elements';

const HEALTH: Record<string, { label: string; variant: 'success' | 'destructive' | 'secondary' | 'outline' }> = {
  live: { label: 'WORKING', variant: 'success' },
  invalid: { label: 'REJECTED', variant: 'destructive' },
  rate_limited: { label: 'THROTTLED', variant: 'secondary' },
  unknown: { label: 'UNUSED', variant: 'outline' },
};

function health(credential: ProviderCredentialOut) {
  if (!credential.enabled) return { label: 'DISABLED', variant: 'outline' as const };
  return HEALTH[credential.status] ?? { label: credential.status.toUpperCase(), variant: 'outline' as const };
}

export function ProviderCredentialsTable({
  rows,
  isLoading,
  isError,
  error,
  onRetry,
  empty,
  actions,
}: {
  rows: ProviderCredentialOut[] | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  onRetry: () => void;
  empty: string;
  actions?: (credential: ProviderCredentialOut) => ReactNode;
}) {
  const columns: Array<Column<ProviderCredentialOut>> = [
    { key: 'provider', header: 'Provider', cellClassName: 'font-medium', cell: (credential) => credential.provider_name },
    { key: 'name', header: 'Name', cell: (credential) => credential.name },
    {
      key: 'key',
      header: 'Key',
      cellClassName: 'font-mono text-xs text-muted-foreground',
      cell: (credential) => <>…{credential.fingerprint}</>,
    },
    { key: 'priority', header: 'Priority', cellClassName: 'text-muted-foreground text-sm', cell: (credential) => credential.priority },
    {
      key: 'health',
      header: 'Status',
      cell: (credential) => {
        const { label, variant } = health(credential);
        return <Badge variant={variant}>{label}</Badge>;
      },
    },
    ...(actions
      ? [
          {
            key: 'actions',
            header: '',
            headClassName: 'w-px',
            cellClassName: 'w-px',
            cell: actions,
          } satisfies Column<ProviderCredentialOut>,
        ]
      : []),
  ];

  return (
    <Card>
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(credential) => credential.id}
        isLoading={isLoading}
        isError={isError}
        error={error}
        resource="provider keys"
        onRetry={onRetry}
        empty={empty}
        emptyIcon={KeyRound}
      />
    </Card>
  );
}
