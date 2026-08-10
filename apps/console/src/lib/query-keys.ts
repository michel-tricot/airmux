/**
 * Centralized org scoping for the query cache.
 *
 * Org-scoped endpoints read their org from the X-Org-Id header, while the generated
 * query keys are the path alone — so every org-scoped query is keyed under
 * ['org-scoped', orgId, ...generatedKey]. Two orgs never share a cache entry, and
 * switching orgs drops everything under ORG_SCOPE_ROOT in one key-based call.
 */
export const ORG_SCOPE_ROOT = ['org-scoped'] as const;

export function orgScopedKey(orgId: string, baseKey: readonly unknown[]): readonly unknown[] {
  return [...ORG_SCOPE_ROOT, orgId, ...baseKey];
}
