import type { ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import { Card } from '@/components/ui/elements';

export function CollapsibleFilterCard({
  children,
  summary,
  onOpenChange,
}: {
  children: ReactNode;
  summary: string;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Card className="p-4">
      <details className="group" onToggle={(event) => onOpenChange(event.currentTarget.open)}>
        <summary className="flex cursor-pointer list-none items-center justify-between rounded text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
          <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            <span>Filters</span>
            <span className="text-xs font-normal text-muted-foreground">{summary}</span>
          </span>
          <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden="true" />
        </summary>
        <div className="mt-4 space-y-4">{children}</div>
      </details>
    </Card>
  );
}
