import { setDefaultHeaders } from '@workspace/api-client-react';

// The control plane's cookie door rejects any request without this header, so it cannot be
// forged from another origin. Set once, for every call the client makes.
setDefaultHeaders(() => ({ 'X-Requested-With': 'XMLHttpRequest' }));

/**
 * A session is user-scoped; the org-scoped endpoints under /v1/org read their scope from
 * X-Org-Id. Pass this as the `request` option, and put the same org in the query key: the
 * generated keys are the path alone, so two orgs would otherwise share one cache entry.
 */
export function orgScope(orgId: string) {
  return { headers: { 'X-Org-Id': orgId } };
}
