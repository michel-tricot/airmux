import type { ModelOut } from '@workspace/api-client-react';
import { Badge } from '@/components/ui/elements';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

function capabilityVariant(capability: string): 'default' | 'warning' | 'success' | 'secondary' {
  if (capability === 'streaming') return 'default';
  if (capability === 'tools') return 'warning';
  return 'secondary';
}

export function ModelBadge({ name, capabilities, className }: { name: string; capabilities?: ModelOut['capabilities']; className?: string }) {
  const badge = (
    <Badge
      variant="outline"
      tabIndex={capabilities === undefined ? undefined : 0}
      className={cn('font-mono focus:ring-0 focus:ring-offset-0 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2', className)}
      title={name}
    >
      <span className="min-w-0 truncate">{name}</span>
    </Badge>
  );
  if (capabilities === undefined) return badge;
  return (
    <Tooltip delayDuration={150}>
      <TooltipTrigger asChild>{badge}</TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-96 border border-border bg-card p-3 text-foreground shadow-xl">
        <div className="mb-1 font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Capabilities</div>
        {capabilities.length ? (
          <div className="flex flex-wrap gap-1.5">
            {capabilities.map((capability) => (
              <Badge key={capability} variant={capabilityVariant(capability)} className="rounded-full px-2 py-0.5 normal-case tracking-normal">
                {capability}
              </Badge>
            ))}
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">None listed</span>
        )}
      </TooltipContent>
    </Tooltip>
  );
}
