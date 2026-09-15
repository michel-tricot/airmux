import { createContext, createElement, useContext, type ReactNode } from 'react';
import { useMyPermissions } from '@workspace/api-client-react';
import { allows, anyOf, type AccessPolicy } from './authorization';
import type { EnabledQueryOptions } from '@/features/query-options';

export type AuthorizationScope =
  | { readonly level: 'instance' }
  | { readonly level: 'org'; readonly orgId: string }
  | { readonly level: 'workspace'; readonly orgId: string; readonly workspaceRef: string };

type AuthorizationLevel = AuthorizationScope['level'];

export function useScopedAuthorization(scope: AuthorizationScope, { enabled = true }: EnabledQueryOptions = {}) {
  const params =
    scope.level === 'instance' ? undefined : { org_id: scope.orgId, ...(scope.level === 'workspace' ? { workspace_ref: scope.workspaceRef } : {}) };
  const query = useMyPermissions(params, { query: { enabled } });
  const permissions = query.data?.permissions ?? [];
  return {
    ...query,
    permissions,
    can: (policy: AccessPolicy) => allows(permissions, policy),
    canAny: (...policies: readonly AccessPolicy[]) => allows(permissions, anyOf(...policies)),
  };
}

type ScopedAuthorization = ReturnType<typeof useScopedAuthorization>;
type AuthorizationContexts = Partial<Record<AuthorizationLevel, ScopedAuthorization>>;

const AuthorizationContext = createContext<AuthorizationContexts>({});

export function AuthorizationProvider({ scope, enabled = true, children }: { scope: AuthorizationScope; enabled?: boolean; children: ReactNode }) {
  const parent = useContext(AuthorizationContext);
  const authorization = useScopedAuthorization(scope, { enabled });
  return createElement(AuthorizationContext.Provider, { value: { ...parent, [scope.level]: authorization } }, children);
}

export function useAuthorization(level: AuthorizationLevel): ScopedAuthorization {
  const authorization = useContext(AuthorizationContext)[level];
  if (!authorization) throw new Error(`${level} authorization scope is required`);
  return authorization;
}
