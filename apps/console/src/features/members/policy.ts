import { operationAuthority } from '@workspace/api-client-react';

export const orgMemberAccess = {
  read: operationAuthority.listOrgUsers,
  add: operationAuthority.addOrgUser,
  remove: operationAuthority.removeOrgUser,
  invite: operationAuthority.createInvitation,
  listInvitations: operationAuthority.listInvitations,
  reissueInvitation: operationAuthority.reissueInvitation,
  revokeInvitation: operationAuthority.revokeInvitation,
} as const;

export const workspaceMemberAccess = {
  read: operationAuthority.listMembers,
  listCandidates: operationAuthority.listMemberCandidates,
  add: operationAuthority.addMember,
  remove: operationAuthority.removeMember,
} as const;
