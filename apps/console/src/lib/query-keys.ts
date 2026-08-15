export const ORG_SCOPE_ROOT = ['org-scoped'] as const;

export function orgScopedKey(orgId: string, baseKey: readonly unknown[]): readonly unknown[] {
  return [...ORG_SCOPE_ROOT, orgId, ...baseKey];
}
