import { SettingsLayout } from '@/components/shared/settings-layout';
import { BundleHistory } from '@/components/shared/bundle-history';
import type { OrgRole } from '@workspace/api-client-react';
import { useChangeOrgRoleMutation, orgRoleOptions } from '@/features/users/hooks';
import { useState } from 'react';
import * as z from 'zod';
import { useRequiredOrgId } from '@/lib/session';
import { useOrgManagementKeys, useCreateOrgManagementKeyMutation, useRevokeOrgManagementKeyMutation } from '@/features/keys/hooks';
import { useCreateOrgServiceAccountMutation, useDeleteOrgServiceAccountMutation, useOrgMembers } from '@/features/members/hooks';
import { useCreateInvitationMutation, useInvitations, useReissueInvitationMutation, useRevokeInvitationMutation } from '@/features/invitations/hooks';
import { useWorkspaces } from '@/features/workspaces/hooks';
import { useBundles, useOrgActivity } from '@/features/telemetry/hooks';
import { Card, Button, Badge, ConfirmButton, Input, TabsContent } from '@/components/ui/elements';
import { Plus, KeyRound, Settings, RefreshCw, UserPlus, Ban, Bot, Trash2 } from 'lucide-react';
import { formatDate } from '@/lib/format';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { PageShell } from '@/components/shared/page-shell';
import { DataTable } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { KeysTable } from '@/components/shared/keys-table';
import { ManagementKeyFormFields, PermissionChecklist, managementKeyFormSchema } from '@/components/shared/management-key-form';
import { ManagementKeyPermissionsCell } from '@/components/shared/management-key-permissions-cell';
import { InvitationDialog, invitationRequest } from '@/components/shared/invitation-dialog';
import { OneTimeValueDialog } from '@/components/shared/one-time-value-dialog';
import { useAuthorization } from '@/features/permissions/hooks';
import { managementKeyAccess } from '@/features/keys/policy';
import { orgMemberAccess } from '@/features/members/policy';
import { telemetryAccess } from '@/features/telemetry/policy';
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from '@/components/ui/form';
import { AccountIdentity, AccountKindBadge } from '@/components/shared/account-display';
import { ActivityTable } from '@/components/shared/activity-table';
import { MembersPanel } from '@/components/shared/members-panel';

const orgServiceAccountSchema = managementKeyFormSchema.extend({
  name: z.string().trim().min(1, 'Name is required').max(200, 'Name must be 200 characters or fewer'),
});

export default function AppOrgSettings() {
  const orgId = useRequiredOrgId();
  const authorization = useAuthorization('org');
  const canReadKeys = authorization.can(managementKeyAccess.org.read);
  const canIssueKey = authorization.can(managementKeyAccess.org.issue);
  const canRevokeKeys = authorization.can(managementKeyAccess.org.revoke);
  const canReadBundles = authorization.can(telemetryAccess.bundles.read);
  const changeRole = useChangeOrgRoleMutation();
  const canChangeRole = authorization.can(orgMemberAccess.add);
  const canReadMembers = authorization.can(orgMemberAccess.read);
  const canListInvitations = authorization.can(orgMemberAccess.listInvitations);
  const canCreateInvitations = authorization.can(orgMemberAccess.invite);
  const canReissueInvitations = authorization.can(orgMemberAccess.reissueInvitation);
  const canRevokeInvitations = authorization.can(orgMemberAccess.revokeInvitation);
  const canCreateServiceAccount = authorization.can(orgMemberAccess.createServiceAccount);
  const canDeleteServiceAccount = authorization.can(orgMemberAccess.deleteServiceAccount);
  const canReadActivity = authorization.can(telemetryAccess.orgActivity);

  const keysQuery = useOrgManagementKeys(orgId, undefined, { enabled: canReadKeys });
  const membersQuery = useOrgMembers(orgId, { enabled: canReadMembers });
  const activityQuery = useOrgActivity(orgId, { limit: 50 }, { enabled: canReadActivity });
  const workspacesQuery = useWorkspaces(orgId, { enabled: canListInvitations || canCreateInvitations });
  const invitationsQuery = useInvitations(orgId, { enabled: canListInvitations });
  const members = membersQuery.data;

  const [keyOpen, setKeyOpen] = useState(false);
  const [keyTarget, setKeyTarget] = useState<{ userId: string; name: string } | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [serviceAccountOpen, setServiceAccountOpen] = useState(false);
  const [invitationUrl, setInvitationUrl] = useState<string | null>(null);

  const keyLabels = new Map(keysQuery.data?.map((key) => [key.id, key.label] as const) ?? []);
  const describeRecord = (entry: { record_id: string }) => keyLabels.get(entry.record_id) ?? null;

  const mintKey = useCreateOrgManagementKeyMutation(orgId);
  const revokeKey = useRevokeOrgManagementKeyMutation(orgId);
  const createInvitation = useCreateInvitationMutation(orgId);
  const reissueInvitation = useReissueInvitationMutation(orgId);
  const revokeInvitation = useRevokeInvitationMutation(orgId);
  const createServiceAccount = useCreateOrgServiceAccountMutation(orgId);
  const deleteServiceAccount = useDeleteOrgServiceAccountMutation(orgId);
  const workspaceNames = new Map(workspacesQuery.data?.map((workspace) => [workspace.id, workspace.name] as const) ?? []);

  const memberActions = (
    <>
      {canCreateServiceAccount && (
        <Button size="sm" variant="outline" onClick={() => setServiceAccountOpen(true)}>
          <Bot className="w-4 h-4 mr-1" /> Create service account
        </Button>
      )}
      {canCreateInvitations && (
        <Button size="sm" onClick={() => setInviteOpen(true)} disabled={workspacesQuery.isLoading || workspacesQuery.isError}>
          <UserPlus className="w-4 h-4 mr-1" /> Invite by email
        </Button>
      )}
    </>
  );

  return (
    <PageShell className="max-w-none space-y-0 p-0 sm:p-0">
      <SettingsLayout
        header={
          <div className="flex items-center gap-4 mb-8">
            <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
              <Settings className="w-6 h-6 text-primary" />
            </div>
            <div>
              <h1 className="text-3xl font-bold tracking-tight">Organization Settings</h1>
              <p className="text-muted-foreground mt-1 text-sm">Manage organization access, members, and activity.</p>
            </div>
          </div>
        }
        categories={[
          ...(canReadKeys ? [{ id: 'keys', label: 'Management Keys' }] : []),
          ...(canReadMembers || canListInvitations ? [{ id: 'members', label: 'Members' }] : []),
          ...(canReadActivity || canReadBundles ? [{ id: 'activity', label: 'Activity' }] : []),
        ]}
      >
        {canReadKeys && (
          <TabsContent value="keys" className="space-y-4 mt-0">
            <div className="flex justify-between items-center mb-4">
              <div>
                <h2 className="text-lg font-semibold">Management Keys</h2>
                <p className="mt-1 text-sm text-muted-foreground">Control-plane API access for managing this organization.</p>
              </div>
              {canIssueKey && (
                <Button
                  onClick={() => {
                    setKeyTarget(null);
                    setKeyOpen(true);
                  }}
                  size="sm"
                  className="shadow-sm"
                >
                  <Plus className="w-4 h-4 mr-1" /> Generate Key
                </Button>
              )}
            </div>
            <KeysTable
              resource="management keys"
              keys={keysQuery.data}
              isLoading={keysQuery.isLoading}
              isError={keysQuery.isError}
              error={keysQuery.error}
              onRetry={() => keysQuery.refetch()}
              emptyText="No management keys generated."
              extraColumns={[
                {
                  key: 'permissions',
                  header: 'Permissions',
                  cell: (key) => <ManagementKeyPermissionsCell apiKey={key} canEdit={authorization.can(managementKeyAccess.org.updatePermissions)} />,
                },
                { key: 'scope', header: 'Scope', cellClassName: 'text-muted-foreground text-sm', cell: (key) => key.scope.level },
              ]}
              revokeDescription="This key and every key delegated from it will stop working immediately."
              onRevoke={canRevokeKeys ? (key) => revokeKey.mutateAsync({ keyId: key.id }) : undefined}
              revokePending={canRevokeKeys ? revokeKey.isPending : undefined}
            />
          </TabsContent>
        )}

        {(canReadMembers || canListInvitations) && (
          <TabsContent value="members" className="space-y-4 mt-0">
            {canReadMembers ? (
              <MembersPanel
                editRole={
                  canChangeRole
                    ? {
                        roles: orgRoleOptions,
                        pending: changeRole.isPending,
                        onSave: (member, role) => changeRole.mutateAsync({ orgId, userId: member.user_id, role: role as OrgRole }),
                      }
                    : undefined
                }
                heading="Organization Members"
                members={members}
                isLoading={membersQuery.isLoading}
                isError={membersQuery.isError}
                error={membersQuery.error}
                onRetry={() => membersQuery.refetch()}
                emptyText="No members found."
                renderName={(member) => <AccountIdentity name={member.name} />}
                actions={memberActions}
                extraColumns={[
                  {
                    key: 'kind',
                    header: 'Kind',
                    headClassName: 'text-right',
                    cellClassName: 'text-right',
                    cell: (member) => <AccountKindBadge serviceAccount={member.service_account} />,
                  },
                  ...(canIssueKey || canDeleteServiceAccount
                    ? [
                        {
                          key: 'actions',
                          header: 'Actions',
                          headClassName: 'text-right',
                          cellClassName: 'text-right',
                          cell: (member: NonNullable<typeof members>[number]) =>
                            member.managed ? (
                              <span className="inline-flex items-center gap-1">
                                {canIssueKey && (
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    aria-label={`Generate replacement key for ${member.name}`}
                                    disabled={mintKey.isPending}
                                    onClick={() => {
                                      setKeyTarget({ userId: member.user_id, name: member.name });
                                      setKeyOpen(true);
                                    }}
                                  >
                                    <KeyRound className="w-4 h-4" />
                                  </Button>
                                )}
                                {canDeleteServiceAccount && (
                                  <ConfirmButton
                                    title={`Delete ${member.name}?`}
                                    description="The service account and all of its control-plane management keys will stop working immediately."
                                    confirmLabel="Delete service account"
                                    pending={deleteServiceAccount.isPending}
                                    aria-label={`Delete service account ${member.name}`}
                                    onConfirm={() => deleteServiceAccount.mutateAsync({ orgId, userId: member.user_id })}
                                  >
                                    <Trash2 className="w-4 h-4" />
                                  </ConfirmButton>
                                )}
                              </span>
                            ) : null,
                        },
                      ]
                    : []),
                ]}
              />
            ) : (
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-lg font-semibold">Organization Invitations</h2>
                <div className="flex items-center gap-2">{memberActions}</div>
              </div>
            )}

            {canListInvitations && (
              <>
                <div className="flex justify-between items-center pt-4">
                  <div>
                    <h2 className="text-lg font-semibold">Pending Invitations</h2>
                    <p className="text-sm text-muted-foreground">Links expire after seven days and can be revoked or replaced.</p>
                  </div>
                </div>
                <Card>
                  <DataTable
                    rows={invitationsQuery.data}
                    rowKey={(invitation) => invitation.id}
                    isLoading={invitationsQuery.isLoading}
                    isError={invitationsQuery.isError}
                    error={invitationsQuery.error}
                    resource="invitations"
                    onRetry={() => invitationsQuery.refetch()}
                    empty="No pending invitations."
                    columns={[
                      { key: 'email', header: 'Email', cellClassName: 'font-medium', cell: (invitation) => invitation.email },
                      {
                        key: 'access',
                        header: 'Access',
                        cellClassName: 'text-muted-foreground',
                        cell: (invitation) =>
                          invitation.workspace_id
                            ? `${invitation.org_role} · ${workspaceNames.get(invitation.workspace_id) ?? 'Workspace'} ${invitation.workspace_role}`
                            : invitation.org_role,
                      },
                      {
                        key: 'expires',
                        header: 'Expires',
                        cellClassName: 'text-muted-foreground text-sm',
                        cell: (invitation) => formatDate(invitation.expires_at),
                      },
                      {
                        key: 'status',
                        header: 'Status',
                        cell: (invitation) => (
                          <Badge variant={invitation.status === 'expired' ? 'destructive' : 'outline'}>{invitation.status}</Badge>
                        ),
                      },
                      {
                        key: 'actions',
                        header: 'Actions',
                        headClassName: 'text-right',
                        cellClassName: 'text-right',
                        cell: (invitation) =>
                          canReissueInvitations || canRevokeInvitations ? (
                            <span className="inline-flex items-center gap-1">
                              {canReissueInvitations && (
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  aria-label={`Reissue invitation for ${invitation.email}`}
                                  disabled={reissueInvitation.isPending}
                                  onClick={async () => {
                                    const minted = await reissueInvitation.mutateAsync({ orgId, invitationId: invitation.id });
                                    setInvitationUrl(minted.url);
                                  }}
                                >
                                  <RefreshCw className="w-4 h-4" />
                                </Button>
                              )}
                              {canRevokeInvitations && (
                                <ConfirmButton
                                  title={`Revoke invitation for ${invitation.email}?`}
                                  description="The shared link will stop working immediately."
                                  confirmLabel="Revoke invitation"
                                  pending={revokeInvitation.isPending}
                                  aria-label={`Revoke invitation for ${invitation.email}`}
                                  onConfirm={() => revokeInvitation.mutateAsync({ orgId, invitationId: invitation.id })}
                                >
                                  <Ban className="w-4 h-4" />
                                </ConfirmButton>
                              )}
                            </span>
                          ) : null,
                      },
                    ]}
                  />
                </Card>
              </>
            )}
          </TabsContent>
        )}

        {(canReadActivity || canReadBundles) && (
          <TabsContent value="activity" className="space-y-4 mt-0">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-semibold">Activity</h2>
            </div>
            {canReadActivity && (
              <Card>
                <ActivityTable
                  entries={activityQuery.data}
                  isLoading={activityQuery.isLoading}
                  isError={activityQuery.isError}
                  error={activityQuery.error}
                  onRetry={() => activityQuery.refetch()}
                  emptyText="Nothing has changed in this org yet."
                  recordLabel={describeRecord}
                  renderActor={(entry) => members?.find((member) => member.user_id === entry.user_id)?.email ?? entry.user_id}
                />
              </Card>
            )}
            {canReadBundles && <ConfigurationHistory orgId={orgId} />}
          </TabsContent>
        )}
      </SettingsLayout>

      {canIssueKey && (
        <FormDialog
          open={keyOpen}
          onOpenChange={(open) => {
            setKeyOpen(open);
            if (!open) setKeyTarget(null);
          }}
          title={keyTarget ? `Generate a replacement key for ${keyTarget.name}` : 'Generate Management Key'}
          description={
            keyTarget
              ? 'The new key is shown once and does not revoke any existing keys for this service account.'
              : 'The key is bound to this organization and carries only the permissions you name.'
          }
          schema={managementKeyFormSchema}
          defaultValues={{ label: '', permissions: [] }}
          onSubmit={async (values) => {
            const minted = await mintKey.mutateAsync({
              orgId,
              data: {
                ...(keyTarget ? { user_id: keyTarget.userId } : {}),
                label: values.label,
                permissions: values.permissions,
              },
            });
            setToken(minted.token);
          }}
          submitLabel={keyTarget ? 'Generate replacement key' : 'Generate'}
          pending={mintKey.isPending}
          submitDisabled={authorization.isFetching || authorization.isError || !canIssueKey}
        >
          {(form) => (
            <ManagementKeyFormFields
              form={form}
              availablePermissions={authorization.permissions}
              canIssue={canIssueKey}
              permissionsLoading={authorization.isFetching}
            />
          )}
        </FormDialog>
      )}

      <KeyRevealDialog open={!!token} onOpenChange={(v) => !v && setToken(null)} token={token} />

      {canCreateServiceAccount && (
        <FormDialog
          open={serviceAccountOpen}
          onOpenChange={setServiceAccountOpen}
          title="Create a service account"
          description="This creates an organization admin for automation and a management key shown only once."
          schema={orgServiceAccountSchema}
          defaultValues={{ name: '', label: '', permissions: [] }}
          onSubmit={async (values) => {
            const minted = await createServiceAccount.mutateAsync({
              orgId,
              data: { name: values.name, management_key: { label: values.label, permissions: values.permissions } },
            });
            setToken(minted.management_key.token);
          }}
          submitLabel="Create service account"
          pendingLabel="Creating..."
          pending={createServiceAccount.isPending}
          submitDisabled={authorization.isFetching || authorization.isError || !canCreateServiceAccount}
        >
          {(form) => (
            <>
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Service account name</FormLabel>
                    <FormControl>
                      <Input placeholder="e.g. Deploy Bot" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="label"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Key label</FormLabel>
                    <FormControl>
                      <Input placeholder="e.g. deployment-management" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="permissions"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Key permissions</FormLabel>
                    <PermissionChecklist
                      value={field.value}
                      onChange={field.onChange}
                      availablePermissions={authorization.permissions}
                      canIssue={canCreateServiceAccount}
                      permissionsLoading={authorization.isFetching}
                      permissionsError={authorization.error}
                      onPermissionsRetry={() => authorization.refetch()}
                    />
                    <FormMessage />
                  </FormItem>
                )}
              />
            </>
          )}
        </FormDialog>
      )}

      {canCreateInvitations && (
        <InvitationDialog
          open={inviteOpen}
          onOpenChange={setInviteOpen}
          workspaces={workspacesQuery.data ?? []}
          pending={createInvitation.isPending}
          onSubmit={async (values) => {
            const minted = await createInvitation.mutateAsync({ orgId, data: invitationRequest(values) });
            setInvitationUrl(minted.url);
          }}
        />
      )}

      <OneTimeValueDialog
        open={invitationUrl !== null}
        onOpenChange={(open) => !open && setInvitationUrl(null)}
        value={invitationUrl}
        title="Invitation link created"
        warning="Share this link through a trusted channel. It will not be shown again."
        label="Invitation link"
        copyLabel="Copy link"
      />
    </PageShell>
  );
}

function ConfigurationHistory({ orgId }: { orgId: string }) {
  const bundlesQuery = useBundles(orgId);
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Configuration history</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Configuration bundles are generated automatically when organization configuration changes.
        </p>
      </div>
      <BundleHistory
        bundles={bundlesQuery.data}
        isLoading={bundlesQuery.isLoading}
        isError={bundlesQuery.isError}
        error={bundlesQuery.error}
        onRetry={() => bundlesQuery.refetch()}
      />
    </section>
  );
}
