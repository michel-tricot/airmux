import { setDefaultHeaders } from '@workspace/api-client-react';

setDefaultHeaders(() => ({ 'X-Requested-With': 'XMLHttpRequest' }));

export function orgScope(orgId: string) {
  return { headers: { 'X-Org-Id': orgId } };
}
