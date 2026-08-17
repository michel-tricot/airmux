import type { Permission } from '@workspace/api-client-react';

export function groupPermissions(permissions: readonly Permission[]): Array<readonly [string, readonly Permission[]]> {
  const resources = [...new Set(permissions.map((permission) => permission.slice(0, permission.indexOf('.'))))];
  return resources.map((resource) => [resource, permissions.filter((permission) => permission.startsWith(`${resource}.`))] as const);
}
