import { useEndPlaygroundSession, useEnsurePlaygroundSession } from '@workspace/api-client-react';

export function useEnsurePlaygroundSessionMutation() {
  return useEnsurePlaygroundSession({ mutation: { meta: { silentError: true } } });
}

export function useEndPlaygroundSessionMutation() {
  return useEndPlaygroundSession({ mutation: { meta: { silentError: true } } });
}
