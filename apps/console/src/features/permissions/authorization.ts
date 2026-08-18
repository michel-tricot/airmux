import type { OperationAuthority, Permission } from '@workspace/api-client-react';

export type AccessPolicy = OperationAuthority | { readonly anyOf: readonly AccessPolicy[] } | { readonly allOf: readonly AccessPolicy[] };

export function anyOf(...policies: readonly AccessPolicy[]): AccessPolicy {
  return { anyOf: policies };
}

export function allOf(...policies: readonly AccessPolicy[]): AccessPolicy {
  return { allOf: policies };
}

export function allows(permissions: readonly Permission[] | undefined, policy: AccessPolicy): boolean {
  const available = new Set(permissions);
  return evaluate(available, policy);
}

function evaluate(permissions: ReadonlySet<Permission>, policy: AccessPolicy): boolean {
  if ('checks' in policy) return policy.checks.every((check) => check.anyOf.some((permission) => permissions.has(permission)));
  if ('anyOf' in policy) return policy.anyOf.some((candidate) => evaluate(permissions, candidate));
  return policy.allOf.every((candidate) => evaluate(permissions, candidate));
}
