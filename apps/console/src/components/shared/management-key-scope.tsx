import type { Scope } from '@workspace/api-client-react';
import { Badge } from '@/components/ui/elements';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

export function ManagementKeyScope({ scope }: { scope: Scope }) {
  return (
    <Tooltip>
      <TooltipTrigger
        type="button"
        aria-label={`Show ${scope.level} target`}
        className="inline-flex items-center rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Badge variant="secondary">{scope.level}</Badge>
      </TooltipTrigger>
      <TooltipContent className="max-w-80 break-all font-mono">{scope.workspace_id ?? scope.org_id ?? 'This instance'}</TooltipContent>
    </Tooltip>
  );
}
