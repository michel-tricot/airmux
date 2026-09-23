import type { ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import { Card } from '@/components/ui/elements';

export function CollapsibleFilterCard({ children }: { children: ReactNode }) {
  return (
    <Card className="p-4">
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center justify-between rounded text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
          Filters
          <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden="true" />
        </summary>
        <div className="mt-4 space-y-4">{children}</div>
      </details>
    </Card>
  );
}
