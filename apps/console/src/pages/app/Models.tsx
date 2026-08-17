import { useState } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown, Boxes, Search } from 'lucide-react';
import { type ModelOut, type ProviderOut, useGetOrgTaxonomy } from '@workspace/api-client-react';
import { ProviderIcon } from '@/components/ProviderIcon';
import { DataTable, type Column } from '@/components/shared/data-table';
import { PageShell } from '@/components/shared/page-shell';
import { Badge, Button, Card, Dropdown } from '@/components/ui/elements';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { useRequiredOrgId } from '@/lib/session';

type SortKey =
  | 'name'
  | 'provider'
  | 'context_window'
  | 'max_output_tokens'
  | 'input_price_per_mtok'
  | 'output_price_per_mtok'
  | 'cache_read_price_per_mtok'
  | 'cache_write_price_per_mtok';

type SortDirection = 'ascending' | 'descending';

interface CatalogModel {
  model: ModelOut;
  provider: ProviderOut | undefined;
}

const numberFormatter = new Intl.NumberFormat('en-US');
const priceFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});
const nameCollator = new Intl.Collator('en-US', { numeric: true, sensitivity: 'base' });
const ALL_FILTERS = 'all';

function modelSortValue(catalogModel: CatalogModel, key: SortKey): string | number | null {
  if (key === 'name') return catalogModel.model.name;
  if (key === 'provider') return catalogModel.provider?.name ?? '';
  return catalogModel.model[key];
}

function compareModels(left: CatalogModel, right: CatalogModel, key: SortKey, direction: SortDirection): number {
  const leftValue = modelSortValue(left, key);
  const rightValue = modelSortValue(right, key);
  if (leftValue === null) return rightValue === null ? 0 : 1;
  if (rightValue === null) return -1;
  const comparison =
    typeof leftValue === 'number' && typeof rightValue === 'number'
      ? leftValue - rightValue
      : nameCollator.compare(String(leftValue), String(rightValue));
  return direction === 'ascending' ? comparison : -comparison;
}

function SortableHeader({
  label,
  sortKey,
  activeKey,
  direction,
  align = 'left',
  onSort,
}: {
  label: string;
  sortKey: SortKey;
  activeKey: SortKey;
  direction: SortDirection;
  align?: 'left' | 'right';
  onSort: (key: SortKey) => void;
}) {
  const active = sortKey === activeKey;
  const Icon = active ? (direction === 'ascending' ? ArrowUp : ArrowDown) : ArrowUpDown;
  const currentDirection = active ? `, currently ${direction}` : '';

  return (
    <Button
      variant="ghost"
      size="sm"
      aria-label={`Sort by ${label}${currentDirection}`}
      onClick={() => onSort(sortKey)}
      className={align === 'right' ? 'ml-auto -mr-3 h-8 gap-1.5 px-3' : '-ml-3 h-8 gap-1.5 px-3'}
    >
      {label}
      <Icon className="h-3.5 w-3.5 text-muted-foreground" />
    </Button>
  );
}

export default function Models() {
  const orgId = useRequiredOrgId();
  const taxonomy = useGetOrgTaxonomy(orgId);
  const [filter, setFilter] = useState('');
  const [providerFilter, setProviderFilter] = useState(ALL_FILTERS);
  const [capabilityFilter, setCapabilityFilter] = useState(ALL_FILTERS);
  const [sortKey, setSortKey] = useState<SortKey>('name');
  const [sortDirection, setSortDirection] = useState<SortDirection>('ascending');
  const providersById = new Map(taxonomy.data?.providers.map((provider) => [provider.id, provider]));
  const catalog = taxonomy.data?.models.map((model) => ({ model, provider: providersById.get(model.provider_id) }));
  const normalizedFilter = filter.trim().toLocaleLowerCase();
  const providerOptions = [
    { value: ALL_FILTERS, label: 'All providers' },
    ...[...(taxonomy.data?.providers ?? [])]
      .sort((left, right) => nameCollator.compare(left.name, right.name))
      .map((provider) => ({ value: provider.id, label: provider.name })),
  ];
  const capabilityOptions = [
    { value: ALL_FILTERS, label: 'All capabilities' },
    ...[...new Set(taxonomy.data?.models.flatMap((model) => model.capabilities) ?? [])]
      .sort(nameCollator.compare)
      .map((capability) => ({ value: capability, label: capability })),
  ];
  const filteredModels = catalog
    ?.filter(({ model }) => model.name.toLocaleLowerCase().includes(normalizedFilter))
    .filter(({ model }) => providerFilter === ALL_FILTERS || model.provider_id === providerFilter)
    .filter(({ model }) => capabilityFilter === ALL_FILTERS || model.capabilities.includes(capabilityFilter))
    .sort((left, right) => compareModels(left, right, sortKey, sortDirection));

  const sort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDirection((current) => (current === 'ascending' ? 'descending' : 'ascending'));
      return;
    }
    setSortKey(key);
    setSortDirection('ascending');
  };

  const header = (label: string, key: SortKey, align?: 'left' | 'right') => (
    <SortableHeader label={label} sortKey={key} activeKey={sortKey} direction={sortDirection} align={align} onSort={sort} />
  );
  const sortDirectionFor = (key: SortKey) => (sortKey === key ? sortDirection : undefined);
  const columns: Array<Column<CatalogModel>> = [
    {
      key: 'model',
      header: header('Model', 'name'),
      sortDirection: sortDirectionFor('name'),
      cell: ({ model }) => (
        <div className="min-w-48">
          <div className="font-mono text-sm font-medium text-foreground">{model.name}</div>
          {model.capabilities.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {model.capabilities.map((capability) => (
                <Badge key={capability} variant="secondary" className="rounded-full px-2 py-0.5 normal-case tracking-normal">
                  {capability}
                </Badge>
              ))}
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'provider',
      header: header('Provider', 'provider'),
      sortDirection: sortDirectionFor('provider'),
      cell: ({ provider }) => (
        <div className="flex items-center gap-2 font-medium">
          {provider?.icon && <ProviderIcon markup={provider.icon} />}
          {provider?.name ?? 'Unknown provider'}
        </div>
      ),
    },
    {
      key: 'context-window',
      header: header('Context window', 'context_window', 'right'),
      sortDirection: sortDirectionFor('context_window'),
      headClassName: 'text-right',
      cellClassName: 'text-right font-mono text-sm tabular-nums',
      cell: ({ model }) => numberFormatter.format(model.context_window),
    },
    {
      key: 'max-output',
      header: header('Max output', 'max_output_tokens', 'right'),
      sortDirection: sortDirectionFor('max_output_tokens'),
      headClassName: 'text-right',
      cellClassName: 'text-right font-mono text-sm tabular-nums',
      cell: ({ model }) => (model.max_output_tokens === null ? 'N/A' : numberFormatter.format(model.max_output_tokens)),
    },
    {
      key: 'input-price',
      header: header('Input price', 'input_price_per_mtok', 'right'),
      sortDirection: sortDirectionFor('input_price_per_mtok'),
      headClassName: 'text-right',
      cellClassName: 'text-right font-mono text-sm tabular-nums',
      cell: ({ model }) => priceFormatter.format(model.input_price_per_mtok),
    },
    {
      key: 'output-price',
      header: header('Output price', 'output_price_per_mtok', 'right'),
      sortDirection: sortDirectionFor('output_price_per_mtok'),
      headClassName: 'text-right',
      cellClassName: 'text-right font-mono text-sm tabular-nums',
      cell: ({ model }) => priceFormatter.format(model.output_price_per_mtok),
    },
    {
      key: 'cache-read-price',
      header: header('Cache read price', 'cache_read_price_per_mtok', 'right'),
      sortDirection: sortDirectionFor('cache_read_price_per_mtok'),
      headClassName: 'text-right',
      cellClassName: 'text-right font-mono text-sm tabular-nums',
      cell: ({ model }) => priceFormatter.format(model.cache_read_price_per_mtok),
    },
    {
      key: 'cache-write-price',
      header: header('Cache write price', 'cache_write_price_per_mtok', 'right'),
      sortDirection: sortDirectionFor('cache_write_price_per_mtok'),
      headClassName: 'text-right',
      cellClassName: 'text-right font-mono text-sm tabular-nums',
      cell: ({ model }) => priceFormatter.format(model.cache_write_price_per_mtok),
    },
  ];

  return (
    <PageShell className="max-w-[100rem]">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Models</h1>
        <p className="mt-1 text-sm text-muted-foreground">Models available across this organization, with limits and prices per million tokens.</p>
      </div>

      <Card>
        <div className="flex flex-col gap-3 border-b border-border p-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-1 flex-col gap-3 sm:flex-row sm:flex-wrap">
            <InputGroup className="w-full bg-background/50 sm:max-w-sm sm:flex-1">
              <InputGroupAddon>
                <Search />
              </InputGroupAddon>
              <InputGroupInput
                aria-label="Filter models"
                placeholder="Search models..."
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                className="font-mono"
              />
            </InputGroup>
            <Dropdown
              aria-label="Filter by provider"
              value={providerFilter}
              onValueChange={setProviderFilter}
              options={providerOptions}
              disabled={!catalog?.length}
              className="w-full sm:w-48"
            />
            <Dropdown
              aria-label="Filter by capability"
              value={capabilityFilter}
              onValueChange={setCapabilityFilter}
              options={capabilityOptions}
              disabled={!catalog?.length}
              className="w-full sm:w-52"
            />
          </div>
          {catalog && (
            <span className="shrink-0 font-mono text-xs text-muted-foreground">
              {filteredModels?.length ?? 0} of {catalog.length} models
            </span>
          )}
        </div>

        <DataTable
          rows={filteredModels}
          rowKey={({ model }) => model.id}
          isLoading={taxonomy.isLoading}
          isError={taxonomy.isError}
          error={taxonomy.error}
          resource="model catalog"
          onRetry={() => taxonomy.refetch()}
          loadingLabel="Loading models..."
          empty={catalog?.length === 0 ? 'No models are available to this organization.' : 'No models match these filters.'}
          emptyIcon={Boxes}
          columns={columns}
        />
      </Card>
    </PageShell>
  );
}
