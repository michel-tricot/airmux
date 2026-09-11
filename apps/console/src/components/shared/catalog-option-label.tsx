import { ProviderIcon } from '@/components/ProviderIcon';

export function CatalogOptionLabel({ name, providerName, providerIcon }: { name: string; providerName?: string; providerIcon?: string }) {
  return (
    <span aria-label={providerName ? `${name}, ${providerName}` : name} className="flex min-w-0 flex-1 items-center gap-2">
      {providerIcon && <ProviderIcon markup={providerIcon} />}
      <span className="truncate">{name}</span>
      {providerName && <span className="ml-auto text-[10px] text-muted-foreground">{providerName}</span>}
    </span>
  );
}
