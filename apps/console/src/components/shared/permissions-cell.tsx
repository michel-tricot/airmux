import { Permission, type Permission as PermissionName } from '@workspace/api-client-react';
import { Badge } from '@/components/ui/elements';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { groupPermissions } from '@/components/shared/permission-groups';

const allPermissions = Object.values(Permission);
const VISIBLE_GROUPS = 1;

export function PermissionsCell({ permissions, compact = false }: { permissions: readonly PermissionName[]; compact?: boolean }) {
  if (permissions.length === 0) {
    return <span className="text-xs text-muted-foreground">No permissions</span>;
  }
  if (permissions.length >= allPermissions.length && allPermissions.every((permission) => permissions.includes(permission))) {
    return <Badge variant="secondary">FULL ACCESS</Badge>;
  }
  const groups = groupPermissions(permissions).map(
    ([resource, grouped]) => [resource, grouped.map((permission) => permission.slice(resource.length + 1))] as const,
  );
  const visible = groups.slice(0, VISIBLE_GROUPS);
  const hidden = groups.length - visible.length;
  return (
    <Tooltip>
      <TooltipTrigger
        type="button"
        aria-label={`Show all ${permissions.length} permissions`}
        className="inline-flex shrink-0 cursor-default items-center whitespace-nowrap gap-1 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {compact ? (
          <span className="text-xs">
            {permissions.length} {permissions.length === 1 ? 'permission' : 'permissions'}
          </span>
        ) : (
          visible.map(([resource, actions]) => (
            <Badge key={resource} variant="outline" className="gap-1 font-mono text-[10px]">
              {resource}
              <span className="text-muted-foreground">{actions.length}</span>
            </Badge>
          ))
        )}
        {!compact && hidden > 0 && <span className="text-xs text-muted-foreground">+{hidden} more</span>}
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
