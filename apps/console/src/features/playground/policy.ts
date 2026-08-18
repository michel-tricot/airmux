import { operationAuthority } from '@workspace/api-client-react';

export const playgroundAccess = {
  execute: operationAuthority.ensurePlaygroundSession,
} as const;
