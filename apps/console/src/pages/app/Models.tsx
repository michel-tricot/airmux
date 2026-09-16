import { useState } from 'react';
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  ArrowUpDown,
  AudioLines,
  Boxes,
  Building2,
  FileText,
  Image as ImageIcon,
  Type as TextIcon,
  Video,
  Wrench,
  X,
} from 'lucide-react';
import { type ModelOut, type ProviderOut, useGetOrgTaxonomy } from '@workspace/api-client-react';
import { ProviderIcon } from '@/components/ProviderIcon';
import { DataTable, type Column } from '@/components/shared/data-table';
import { ModelBadge } from '@/components/shared/model-badge';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { SearchField } from '@/components/shared/search-field';
import { Badge, Button, Card, CheckboxDropdown } from '@/components/ui/elements';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useRequiredOrgId } from '@/lib/session';
import { cn } from '@/lib/utils';
import { formatUsdRate, parseUsdRate } from '@/lib/money';

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
const nameCollator = new Intl.Collator('en-US', { numeric: true, sensitivity: 'base' });
type Modality = ModelOut['input_modalities'][number] | ModelOut['output_modalities'][number];

function ModalityIcon({ modality }: { modality: Modality }) {
  const Icon =
    modality === 'image' ? ImageIcon : modality === 'audio' ? AudioLines : modality === 'video' ? Video : modality === 'pdf' ? FileText : TextIcon;
  return <Icon aria-hidden="true" className="h-3.5 w-3.5" />;
}

function ModalityMarker({ direction, modality }: { direction: 'Input' | 'Output'; modality: Modality }) {
  const label = `${direction} modality: ${modality}`;
  const tooltip = `${direction}: ${modality.charAt(0).toLocaleUpperCase()}${modality.slice(1)}`;

  return (
    <Tooltip delayDuration={150}>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={label}
          className={cn(
            'h-6 w-6 rounded-sm',
            direction === 'Input' ? 'text-success hover:bg-success/10 hover:text-success' : 'text-primary hover:text-primary',
          )}
        >
          <ModalityIcon modality={modality} />
        </Button>
      </TooltipTrigger>
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  );
}

function ModalityGroup({ direction, modalities }: { direction: 'Input' | 'Output'; modalities: Modality[] }) {
  return (
    <div aria-label={`${direction} modalities`} className="flex items-center gap-0.5">
      {modalities.map((modality) => (
        <ModalityMarker key={modality} direction={direction} modality={modality} />
      ))}
    </div>
  );
}

function ModalityFlow({
  input_modalities: inputModalities,
  output_modalities: outputModalities,
}: Pick<ModelOut, 'input_modalities' | 'output_modalities'>) {
  return (
    <div aria-label="Input to output modalities" className="flex items-center gap-1 pl-0.5">
      <ModalityGroup direction="Input" modalities={inputModalities} />
      <ArrowRight aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
      <ModalityGroup direction="Output" modalities={outputModalities} />
    </div>
  );
}

function modelSortValue(catalogModel: CatalogModel, key: SortKey): string | number | bigint | null {
  if (key === 'name') return catalogModel.model.name;
  if (key === 'provider') return catalogModel.provider?.name ?? '';
  if (key.endsWith('_price_per_mtok')) return parseUsdRate(String(catalogModel.model[key]));
  return catalogModel.model[key];
}

function compareModels(left: CatalogModel, right: CatalogModel, key: SortKey, direction: SortDirection): number {
  const leftValue = modelSortValue(left, key);
  const rightValue = modelSortValue(right, key);
  if (leftValue === null) return rightValue === null ? 0 : 1;
  if (rightValue === null) return -1;
  const comparison =
    typeof leftValue === 'bigint' && typeof rightValue === 'bigint'
      ? leftValue < rightValue
        ? -1
        : leftValue > rightValue
          ? 1
          : 0
      : typeof leftValue === 'number' && typeof rightValue === 'number'
        ? leftValue - rightValue
        : nameCollator.compare(String(leftValue), String(rightValue));
  return direction === 'ascending' ? comparison : -comparison;
}

function supportsModality(model: ModelOut, value: string): boolean {
  const [direction, modality] = value.split(':');
  const modalities = direction === 'input' ? model.input_modalities : model.output_modalities;
  return modalities.some((candidate) => candidate === modality);
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
      className={cn(align === 'right' ? 'ml-auto -mr-3 h-8 gap-1.5 px-3' : '-ml-3 h-8 gap-1.5 px-3', active && 'text-primary')}
    >
      {label}
      <Icon className={cn('h-3.5 w-3.5', active ? 'text-primary' : 'text-muted-foreground')} />
    </Button>
  );
}

export default function Models() {
  const orgId = useRequiredOrgId();
  const taxonomy = useGetOrgTaxonomy(orgId);
  const [filter, setFilter] = useState('');
  const [providerFilters, setProviderFilters] = useState<string[]>([]);
  const [capabilityFilters, setCapabilityFilters] = useState<string[]>([]);
  const [modalityFilters, setModalityFilters] = useState<string[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>('name');
  const [sortDirection, setSortDirection] = useState<SortDirection>('ascending');
  const providersById = new Map(taxonomy.data?.providers.map((provider) => [provider.id, provider]));
  const catalog = taxonomy.data?.models.map((model) => ({ model, provider: providersById.get(model.provider_id) }));
  const providerCount = taxonomy.data?.providers.length ?? 0;
  const toolCapableModels = catalog?.filter(({ model }) => model.capabilities.includes('tools')).length ?? 0;
  const normalizedFilter = filter.trim().toLocaleLowerCase();
  const hasActiveFilters = normalizedFilter.length > 0 || providerFilters.length > 0 || capabilityFilters.length > 0 || modalityFilters.length > 0;
  const providerOptions = [...(taxonomy.data?.providers ?? [])]
    .sort((left, right) => nameCollator.compare(left.name, right.name))
    .map((provider) => ({ value: provider.id, label: provider.name }));
  const capabilityOptions = [...new Set(taxonomy.data?.models.flatMap((model) => model.capabilities) ?? [])]
    .sort(nameCollator.compare)
    .map((capability) => ({ value: capability, label: capability }));
  const modalityOptions = [
    ...new Set(
      taxonomy.data?.models.flatMap((model) => [
        ...(model.input_modalities ?? []).map((modality) => `input:${modality}`),
        ...(model.output_modalities ?? []).map((modality) => `output:${modality}`),
      ]) ?? [],
    ),
  ]
    .sort(nameCollator.compare)
    .map((value) => {
      const [direction, modality] = value.split(':');
      return { value, label: `${direction === 'input' ? 'Input' : 'Output'}: ${modality}` };
    });
  const filteredModels = catalog
    ?.filter(({ model }) => model.name.toLocaleLowerCase().includes(normalizedFilter))
    .filter(({ model }) => providerFilters.length === 0 || providerFilters.includes(model.provider_id))
    .filter(({ model }) => capabilityFilters.every((capability) => model.capabilities.some((candidate) => candidate === capability)))
    .filter(({ model }) => modalityFilters.every((modality) => supportsModality(model, modality)))
    .sort((left, right) => compareModels(left, right, sortKey, sortDirection));

  const sort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDirection((current) => (current === 'ascending' ? 'descending' : 'ascending'));
      return;
    }
    setSortKey(key);
    setSortDirection('ascending');
  };

  const clearFilters = () => {
    setFilter('');
    setProviderFilters([]);
    setCapabilityFilters([]);
    setModalityFilters([]);
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
      cellClassName: 'min-w-48',
      cell: ({ model }) => (
        <div className="space-y-1.5">
          <ModelBadge name={model.name} capabilities={model.capabilities} />
          <ModalityFlow input_modalities={model.input_modalities} output_modalities={model.output_modalities} />
        </div>
      ),
    },
    {
      key: 'provider',
      header: header('Provider', 'provider'),
      sortDirection: sortDirectionFor('provider'),
      cell: ({ provider }) => (
        <div className="flex items-center gap-3 font-medium">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-primary/20 bg-primary/10 text-primary">
            {provider?.icon ? (
              <ProviderIcon markup={provider.icon} />
            ) : (
              <span className="font-mono text-xs font-bold">{provider?.name.at(0)?.toUpperCase() ?? '?'}</span>
            )}
          </span>
          <span>{provider?.name ?? 'Unknown provider'}</span>
        </div>
      ),
    },
    {
      key: 'context-window',
      header: header('Context window', 'context_window', 'right'),
      sortDirection: sortDirectionFor('context_window'),
      headClassName: 'border-l border-primary/20 text-right',
      cellClassName: 'border-l border-primary/10 text-right font-mono text-sm tabular-nums',
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
      headClassName: 'border-l border-warning/20 text-right',
      cellClassName: 'border-l border-warning/10 text-right font-mono text-sm tabular-nums',
      cell: ({ model }) => `$${formatUsdRate(parseUsdRate(model.input_price_per_mtok))}`,
    },
    {
      key: 'output-price',
      header: header('Output price', 'output_price_per_mtok', 'right'),
      sortDirection: sortDirectionFor('output_price_per_mtok'),
      headClassName: 'text-right',
      cellClassName: 'text-right font-mono text-sm tabular-nums',
      cell: ({ model }) => `$${formatUsdRate(parseUsdRate(model.output_price_per_mtok))}`,
    },
    {
      key: 'cache-read-price',
      header: header('Cache read price', 'cache_read_price_per_mtok', 'right'),
      sortDirection: sortDirectionFor('cache_read_price_per_mtok'),
      headClassName: 'text-right',
      cellClassName: 'text-right font-mono text-sm tabular-nums',
      cell: ({ model }) => `$${formatUsdRate(parseUsdRate(model.cache_read_price_per_mtok))}`,
    },
    {
      key: 'cache-write-price',
      header: header('Cache write price', 'cache_write_price_per_mtok', 'right'),
      sortDirection: sortDirectionFor('cache_write_price_per_mtok'),
      headClassName: 'text-right',
      cellClassName: 'text-right font-mono text-sm tabular-nums',
      cell: ({ model }) => `$${formatUsdRate(parseUsdRate(model.cache_write_price_per_mtok))}`,
    },
  ];

  return (
    <PageShell className="max-w-[100rem]">
      <PageHeader title="Models" description="Models available across this organization, with limits and prices per million tokens." />

      {catalog && (
        <Card aria-label="Catalog summary" className="grid overflow-hidden sm:grid-cols-3">
          <div aria-label={`${catalog.length} models`} className="flex items-center gap-3 bg-primary/[0.07] p-4">
            <span className="flex h-10 w-10 items-center justify-center rounded-md border border-primary/25 bg-primary/10 text-primary">
              <Boxes className="h-5 w-5" />
            </span>
            <div>
              <div className="font-mono text-2xl font-bold tabular-nums">{numberFormatter.format(catalog.length)}</div>
              <div className="text-xs font-medium text-muted-foreground">Models</div>
            </div>
          </div>
          <div
            aria-label={`${providerCount} providers`}
            className="flex items-center gap-3 border-t border-border bg-muted/20 p-4 sm:border-l sm:border-t-0"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-md border border-warning/25 bg-warning/10 text-warning">
              <Building2 className="h-5 w-5" />
            </span>
            <div>
              <div className="font-mono text-2xl font-bold tabular-nums">{numberFormatter.format(providerCount)}</div>
              <div className="text-xs font-medium text-muted-foreground">Providers</div>
            </div>
          </div>
          <div
            aria-label={`${toolCapableModels} tool-capable models`}
            className="flex items-center gap-3 border-t border-border bg-success/[0.04] p-4 sm:border-l sm:border-t-0"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-md border border-success/25 bg-success/10 text-success">
              <Wrench className="h-5 w-5" />
            </span>
            <div>
              <div className="font-mono text-2xl font-bold tabular-nums">{numberFormatter.format(toolCapableModels)}</div>
              <div className="text-xs font-medium text-muted-foreground">Tool-capable</div>
            </div>
          </div>
        </Card>
      )}

      <Card className="overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-border bg-primary/[0.025] p-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-1 flex-col gap-3 sm:flex-row sm:flex-wrap">
            <SearchField
              value={filter}
              onValueChange={setFilter}
              label="Filter models"
              placeholder="Search models..."
              className="w-full sm:max-w-sm sm:flex-1"
            />
            <CheckboxDropdown
              aria-label="Filter by provider"
              label="Providers"
              allLabel="All providers"
              values={providerFilters}
              onValuesChange={setProviderFilters}
              options={providerOptions}
              disabled={!catalog?.length}
              className="w-full sm:w-48"
            />
            <CheckboxDropdown
              aria-label="Filter by capability"
              label="Capabilities"
              allLabel="All capabilities"
              values={capabilityFilters}
              onValuesChange={setCapabilityFilters}
              options={capabilityOptions}
              disabled={!catalog?.length}
              className="w-full sm:w-52"
            />
            <CheckboxDropdown
              aria-label="Filter by modality"
              label="Modalities"
              allLabel="All modalities"
              values={modalityFilters}
              onValuesChange={setModalityFilters}
              options={modalityOptions}
              disabled={!catalog?.length}
              className="w-full sm:w-48"
            />
            <Button variant="ghost" size="sm" onClick={clearFilters} disabled={!hasActiveFilters} className="h-9 w-full gap-1.5 px-3 sm:w-auto">
              <X className="h-3.5 w-3.5" />
              Clear filters
            </Button>
          </div>
          {catalog && (
            <Badge className="shrink-0 normal-case tracking-normal">
              {filteredModels?.length ?? 0} of {catalog.length} models
            </Badge>
          )}
        </div>

        <DataTable
          headerGroups={[
            { key: 'catalog', label: 'Catalog', colSpan: 2, className: 'bg-muted/30 font-mono text-[10px] font-bold uppercase tracking-widest' },
            {
              key: 'limits',
              label: 'Limits',
              colSpan: 2,
              className: 'border-l border-primary/20 bg-primary/[0.06] font-mono text-[10px] font-bold uppercase tracking-widest text-primary',
            },
            {
              key: 'pricing',
              label: 'Pricing',
              colSpan: 4,
              className: 'border-l border-warning/20 bg-warning/[0.05] font-mono text-[10px] font-bold uppercase tracking-widest text-warning',
            },
          ]}
          rows={filteredModels}
          rowKey={({ model }) => model.id}
          rowClassName="group odd:bg-muted/[0.12] hover:bg-primary/[0.06]"
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
