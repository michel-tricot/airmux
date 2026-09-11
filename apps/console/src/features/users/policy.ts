import { operationAuthority } from '@workspace/api-client-react';

export const userAccess = {
  list: operationAuthority.listUsers,
  read: operationAuthority.getUser,
  createServiceAccount: operationAuthority.createServiceAccount,
  changeRole: operationAuthority.changeInstanceRole,
  delete: operationAuthority.deleteUser,
} as const;
