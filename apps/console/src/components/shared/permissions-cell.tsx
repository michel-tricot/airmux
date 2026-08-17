import { Permission, type Permission as PermissionName } from '@workspace/api-client-react';
import { Badge } from '@/components/ui/elements';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

const allPermissions = Object.values(Permission);
const VISIBLE_GROUPS = 3;

function groupByResource(permissions: readonly PermissionName[]): [string, string[]][] {
  const groups = new Map<string, string[]>();
  for (const permission of permissions) {
    const [resource, action] = permission.split('.');
    const actions = groups.get(resource) ?? [];
    actions.push(action);
    groups.set(resource, actions);
  }
  return [...groups.entries()];
}

export function PermissionsCell({ permissions }: { permissions: readonly PermissionName[] }) {
  if (permissions.length === 0) {
    return <span className="text-xs text-muted-foreground">No permissions</span>;
  }
  if (permissions.length >= allPermissions.length && allPermissions.every((permission) => permissions.includes(permission))) {
    return <Badge variant="secondary">FULL ACCESS</Badge>;
  }
  const groups = groupByResource(permissions);
  const visible = groups.slice(0, VISIBLE_GROUPS);
  const hidden = groups.length - visible.length;
  return (
    <Tooltip>
      <TooltipTrigger
        type="button"
        aria-label={`Show all ${permissions.length} permissions`}
        className="flex max-w-72 cursor-default flex-wrap items-center gap-1 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
          {visible.map(([resource, actions]) => (
            <Badge key={resource} variant="outline" className="gap-1 font-mono text-[10px]">
              {resource}
              <span className="text-muted-foreground">{actions.length}</span>
            </Badge>
          ))}
          {hidden > 0 && <span className="text-xs text-muted-foreground">+{hidden} more</span>}
      </TooltipTrigger>
      <TooltipContent side="left" className="max-w-80">
        <div className="space-y-1 py-1">
          {groups.map(([resource, actions]) => (
            <div key={resource} className="font-mono text-[11px]">
              <span className="font-bold">{resource}</span>
              <span className="opacity-80"> {actions.join(', ')}</span>
            </div>
          ))}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
