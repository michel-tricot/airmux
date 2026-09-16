import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { getListWorkspacesQueryKey, getMyPermissionsQueryKey } from '@workspace/api-client-react';
import type { ReactNode } from 'react';
import { expect, it } from 'vitest';
import { SessionProvider, useSession } from '@/lib/session';

it('evicts departed organization data while retaining another organization cache', () => {
  window.localStorage.setItem('airmux_org_id', 'departed');
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const departed = getListWorkspacesQueryKey('departed');
  const permissions = getMyPermissionsQueryKey({ org_id: 'departed', workspace_ref: 'private' });
  const retained = getListWorkspacesQueryKey('retained');
  queryClient.setQueryData(departed, [{ name: 'private workspace' }]);
  queryClient.setQueryData(permissions, { permissions: ['playground.execute'] });
  queryClient.setQueryData(retained, [{ name: 'retained workspace' }]);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>{children}</SessionProvider>
    </QueryClientProvider>
  );
  const session = renderHook(() => useSession(), { wrapper });
  act(() => session.result.current.setOrgId('retained'));
  expect(queryClient.getQueryData(departed)).toBeUndefined();
  expect(queryClient.getQueryData(permissions)).toBeUndefined();
  expect(queryClient.getQueryData(retained)).toEqual([{ name: 'retained workspace' }]);
  expect(window.localStorage.getItem('airmux_org_id')).toBe('retained');
});
