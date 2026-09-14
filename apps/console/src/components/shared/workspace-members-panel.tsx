import type { ReactNode } from 'react';
import { MembersPanel } from '@/components/shared/members-panel';
import { ErrorState } from '@/components/shared/states';
import {
  useAddWorkspaceMemberMutation,
  useChangeWorkspaceRoleMutation,
  useRemoveWorkspaceMemberMutation,
  useWorkspaceMemberCandidates,
  useWorkspaceMembers,
  workspaceRoleOptions,
} from '@/features/members/hooks';

interface WorkspaceMembersPanelProps {
  orgId: string;
  workspaceRef: string;
  heading: ReactNode;
  actions?: ReactNode;
  canListCandidates: boolean;
  canManageMembers: boolean;
  canRemoveMembers: boolean;
}

export function WorkspaceMembersPanel({
  orgId,
  workspaceRef,
  heading,
  actions,
  canListCandidates,
  canManageMembers,
  canRemoveMembers,
}: WorkspaceMembersPanelProps) {
  const canChooseMembers = canManageMembers && canListCandidates;
  const membersQuery = useWorkspaceMembers(orgId, workspaceRef);
  const candidatesQuery = useWorkspaceMemberCandidates(orgId, workspaceRef, { enabled: canChooseMembers });
  const addMember = useAddWorkspaceMemberMutation(orgId, workspaceRef);
  const removeMember = useRemoveWorkspaceMemberMutation(orgId, workspaceRef);
  const changeRole = useChangeWorkspaceRoleMutation(orgId, workspaceRef);
  const candidates = candidatesQuery.data;

  return (
    <div className="space-y-4">
      <MembersPanel
        heading={heading}
        actions={actions}
        members={membersQuery.data}
        isLoading={membersQuery.isLoading}
        isError={membersQuery.isError}
        error={membersQuery.error}
        onRetry={() => membersQuery.refetch()}
        emptyText="No members in this workspace."
        add={
          canChooseMembers && !candidatesQuery.isError
            ? {
                candidates: candidates?.map((user) => ({ value: user.user_id, label: `${user.name} (${user.email})` })) ?? [],
                dialogTitle: 'Add Member',
                dialogDescription: 'Choose someone who already belongs to this organization.',
                placeholder: 'Select an org member',
                roles: workspaceRoleOptions,
                defaultRole: 'member',
                onAdd: (userId, role) => addMember.mutateAsync({ orgId, workspaceRef, userId, data: { role } }),
                pending: addMember.isPending || candidates === undefined,
              }
            : undefined
        }
        editRole={
          canManageMembers
            ? {
                roles: workspaceRoleOptions,
                pending: changeRole.isPending,
                onSave: (member, role) => changeRole.mutateAsync({ orgId, workspaceRef, userId: member.user_id, data: { role } }),
              }
            : undefined
        }
        remove={
          canRemoveMembers
            ? {
                title: (member) => `Remove ${member.name} from the workspace?`,
                description: 'They lose access to this workspace but stay in the organization.',
                onRemove: (member) => removeMember.mutateAsync({ orgId, workspaceRef, userId: member.user_id }),
                pending: removeMember.isPending,
              }
            : undefined
        }
      />
      {canChooseMembers && candidatesQuery.isError && (
        <ErrorState
          error={candidatesQuery.error}
          message="Member candidates are unavailable. Existing members are still shown."
          onRetry={() => candidatesQuery.refetch()}
          className="p-0"
        />
      )}
    </div>
  );
}
