import { useState } from 'react';
import { useRequiredOrgId } from '@/lib/session';
import { useOrgAccessKeys, useCreateOrgAccessKeyMutation, useRevokeOrgAccessKeyMutation } from '@/features/keys/hooks';
import { useOrgMembers } from '@/features/members/hooks';
import { useCreateInvitationMutation, useInvitations, useReissueInvitationMutation, useRevokeInvitationMutation } from '@/features/invitations/hooks';
import { useWorkspaces } from '@/features/workspaces/hooks';
import { useBundles, useOrgActivity, useRepublishBundleMutation } from '@/features/telemetry/hooks';
import { Avatar, AvatarFallback, Card, Button, Badge, ConfirmButton, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/elements';
import { Plus, Key, Settings, Package, RefreshCw, Users, Activity, UserPlus, Ban } from 'lucide-react';
import { formatDate, formatRelative } from '@/lib/format';
import { KeyRevealDialog } from '@/components/KeyRevealDialog';
import { PageShell } from '@/components/shared/page-shell';
import { DataTable } from '@/components/shared/data-table';
import { FormDialog } from '@/components/shared/form-dialog';
import { ApiKeysTable } from '@/components/shared/api-keys-table';
import { AccessKeyFormFields, accessKeyFormSchema } from '@/components/shared/access-key-form';
import { PermissionsCell } from '@/components/shared/permissions-cell';
import { InvitationDialog, invitationRequest } from '@/components/shared/invitation-dialog';
import { OneTimeValueDialog } from '@/components/shared/one-time-value-dialog';
import { useAuthorization } from '@/features/permissions/hooks';
import { accessKeyAccess } from '@/features/keys/policy';
import { orgMemberAccess } from '@/features/members/policy';
import { telemetryAccess } from '@/features/telemetry/policy';

export default function AppOrgSettings() {
  const orgId = useRequiredOrgId();
  const authorization = useAuthorization('org');
  const canReadKeys = authorization.can(accessKeyAccess.org.read);
  const canIssueKey = authorization.can(accessKeyAccess.org.issue);
  const canRevokeKeys = authorization.can(accessKeyAccess.org.revoke);
  const canReadBundles = authorization.can(telemetryAccess.bundles.read);
  const canPublishBundles = authorization.can(telemetryAccess.bundles.publish);
  const canReadMembers = authorization.can(orgMemberAccess.read);
  const canListInvitations = authorization.can(orgMemberAccess.listInvitations);
  const canCreateInvitations = authorization.can(orgMemberAccess.invite);
  const canReissueInvitations = authorization.can(orgMemberAccess.reissueInvitation);
  const canRevokeInvitations = authorization.can(orgMemberAccess.revokeInvitation);
  const canReadActivity = authorization.can(telemetryAccess.orgActivity);

  const keysQuery = useOrgAccessKeys(orgId, undefined, { enabled: canReadKeys });
  const bundlesQuery = useBundles(orgId, { enabled: canReadBundles });
  const membersQuery = useOrgMembers(orgId, { enabled: canReadMembers });
  const activityQuery = useOrgActivity(orgId, { limit: 50 }, { enabled: canReadActivity });
  const workspacesQuery = useWorkspaces(orgId, { enabled: canListInvitations || canCreateInvitations });
  const invitationsQuery = useInvitations(orgId, { enabled: canListInvitations });
  const members = membersQuery.data;

  const [keyOpen, setKeyOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [invitationUrl, setInvitationUrl] = useState<string | null>(null);

  const keyLabels = new Map(keysQuery.data?.map((key) => [key.id, key.label] as const) ?? []);
  const describeRecord = (entry: { record_id: string }) => keyLabels.get(entry.record_id) ?? null;

  const mintKey = useCreateOrgAccessKeyMutation(orgId);
  const revokeKey = useRevokeOrgAccessKeyMutation(orgId);
  const republish = useRepublishBundleMutation(orgId);
  const createInvitation = useCreateInvitationMutation(orgId);
  const reissueInvitation = useReissueInvitationMutation(orgId);
  const revokeInvitation = useRevokeInvitationMutation(orgId);
  const workspaceNames = new Map(workspacesQuery.data?.map((workspace) => [workspace.id, workspace.name] as const) ?? []);
  const defaultTab = canReadKeys ? 'keys' : canReadBundles ? 'bundles' : canReadMembers || canListInvitations ? 'members' : 'activity';

  return (
    <PageShell className="max-w-5xl">
      <div className="flex items-center gap-4 mb-8">
        <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
          <Settings className="w-6 h-6 text-primary" />
        </div>
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Organization Settings</h1>
          <p className="text-muted-foreground mt-1 text-sm">Manage automation credentials and published organization policies.</p>
        </div>
      </div>

      <Tabs defaultValue={defaultTab} className="w-full">
        <TabsList className="mb-4">
          {canReadKeys && (
            <TabsTrigger value="keys" className="gap-2">
              <Key className="w-4 h-4" /> Automation Keys
            </TabsTrigger>
          )}
          {canReadBundles && (
            <TabsTrigger value="bundles" className="gap-2">
              <Package className="w-4 h-4" /> Policies
            </TabsTrigger>
          )}
          {(canReadMembers || canListInvitations) && (
            <TabsTrigger value="members" className="gap-2">
              <Users className="w-4 h-4" /> Members
            </TabsTrigger>
          )}
          {canReadActivity && (
            <TabsTrigger value="activity" className="gap-2">
              <Activity className="w-4 h-4" /> Activity
            </TabsTrigger>
          )}
        </TabsList>

        {canReadKeys && (
          <TabsContent value="keys" className="space-y-4 mt-0">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-semibold">Automation Keys</h2>
              {canIssueKey && (
                <Button onClick={() => setKeyOpen(true)} size="sm" className="shadow-sm">
                  <Plus className="w-4 h-4 mr-1" /> Generate Key
                </Button>
              )}
            </div>
            <ApiKeysTable
              resource="access keys"
              keys={keysQuery.data}
              isLoading={keysQuery.isLoading}
              isError={keysQuery.isError}
              error={keysQuery.error}
              onRetry={() => keysQuery.refetch()}
              emptyText="No access keys generated."
              extraColumns={[
                {
                  key: 'permissions',
                  header: 'Permissions',
                  cell: (key) => <PermissionsCell permissions={key.permissions} />,
                },
                { key: 'scope', header: 'Scope', cellClassName: 'text-muted-foreground text-sm', cell: (key) => key.scope.level },
              ]}
              revokeDescription="This key and every key delegated from it will stop working immediately."
              onRevoke={canRevokeKeys ? (key) => revokeKey.mutateAsync({ keyId: key.id }) : undefined}
              revokePending={canRevokeKeys ? revokeKey.isPending : undefined}
            />
          </TabsContent>
        )}

        {canReadBundles && (
          <TabsContent value="bundles" className="space-y-4 mt-0">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-semibold">Access Policies</h2>
              {canPublishBundles && (
                <Button onClick={() => republish.mutate({ orgId })} size="sm" disabled={republish.isPending}>
                  <RefreshCw className="w-4 h-4 mr-1" /> {republish.isPending ? 'Republishing...' : 'Republish policy'}
                </Button>
              )}
            </div>
            <Card>
              <DataTable
                rows={bundlesQuery.data ? [...bundlesQuery.data].reverse() : undefined}
                rowKey={(bundle) => bundle.id}
                isLoading={bundlesQuery.isLoading}
                isError={bundlesQuery.isError}
                error={bundlesQuery.error}
                resource="policies"
                onRetry={() => bundlesQuery.refetch()}
                empty="No policies have been published yet."
                columns={[
                  { key: 'version', header: 'Version', cellClassName: 'font-mono font-medium', cell: (bundle) => `v${bundle.version}` },
                  { key: 'id', header: 'Policy ID', cellClassName: 'font-mono text-xs text-muted-foreground', cell: (bundle) => bundle.id },
                  {
                    key: 'published',
                    header: 'Published',
                    cellClassName: 'text-muted-foreground text-sm',
                    cell: (bundle) => formatDate(bundle.issued_at),
                  },
                ]}
              />
            </Card>
          </TabsContent>
        )}

        {(canReadMembers || canListInvitations) && (
          <TabsContent value="members" className="space-y-4 mt-0">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-semibold">{canReadMembers ? 'Organization Members' : 'Organization Invitations'}</h2>
              {canCreateInvitations && (
                <Button size="sm" onClick={() => setInviteOpen(true)} disabled={workspacesQuery.isLoading || workspacesQuery.isError}>
                  <UserPlus className="w-4 h-4 mr-1" /> Invite by email
                </Button>
              )}
            </div>
            {canReadMembers && (
              <Card>
                <DataTable
                  rows={members}
                  rowKey={(member) => member.user_id}
                  isLoading={membersQuery.isLoading}
                  isError={membersQuery.isError}
                  error={membersQuery.error}
                  resource="members"
                  onRetry={() => membersQuery.refetch()}
                  empty="No members found."
                  columns={[
                    {
                      key: 'name',
                      header: 'Name',
                      cellClassName: 'font-medium',
                      cell: (member) => (
                        <span className="flex items-center gap-2">
                          <Avatar aria-hidden="true" className="h-6 w-6">
                            <AvatarFallback className="bg-primary/10 text-xs font-bold text-primary">{member.name.charAt(0)}</AvatarFallback>
                          </Avatar>
                          {member.name}
                        </span>
                      ),
                    },
                    { key: 'email', header: 'Email', cellClassName: 'text-muted-foreground', cell: (member) => member.email },
                    { key: 'role', header: 'Role', cellClassName: 'text-muted-foreground', cell: (member) => member.role },
                    {
                      key: 'kind',
                      header: 'Account type',
                      headClassName: 'text-right',
                      cellClassName: 'text-right',
                      cell: (member) => (
                        <Badge variant={member.service_account ? 'secondary' : 'outline'}>
                          {member.service_account ? 'Service account' : 'User'}
                        </Badge>
                      ),
                    },
                  ]}
                />
              </Card>
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

        {canReadActivity && (
          <TabsContent value="activity" className="space-y-4 mt-0">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-semibold">Recent activity</h2>
            </div>
            <Card>
              <DataTable
                rows={activityQuery.data}
                rowKey={(entry) => String(entry.id)}
                isLoading={activityQuery.isLoading}
                isError={activityQuery.isError}
                error={activityQuery.error}
                resource="activity"
                onRetry={() => activityQuery.refetch()}
                empty="Nothing has changed in this org yet."
                columns={[
                  {
                    key: 'change',
                    header: 'Change',
                    cell: (entry) => (
                      <Badge
                        variant={entry.action === 'delete' ? 'destructive' : entry.action === 'create' ? 'success' : 'secondary'}
                        className="font-mono"
                      >
                        {entry.action}
                      </Badge>
                    ),
                  },
                  {
                    key: 'item',
                    header: 'Item',
                    cellClassName: 'font-medium',
                    cell: (entry) => {
                      const label = describeRecord(entry);
                      return (
                        <>
                          {entry.table_name}
                          {label && <span className="ml-2 text-muted-foreground">“{label}”</span>}
                          <div className="text-xs text-muted-foreground font-mono">{entry.record_id}</div>
                        </>
                      );
                    },
                  },
                  {
                    key: 'actor',
                    header: 'Changed by',
                    cellClassName: 'font-mono text-xs text-muted-foreground',
                    cell: (entry) => members?.find((m) => m.user_id === entry.user_id)?.email ?? entry.user_id,
                  },
                  {
                    key: 'when',
                    header: 'When',
                    headClassName: 'text-right',
                    cellClassName: 'text-right text-muted-foreground text-sm',
                    cell: (entry) => formatRelative(entry.occurred_at),
                  },
                ]}
              />
            </Card>
          </TabsContent>
        )}
      </Tabs>

      {canIssueKey && (
        <FormDialog
          open={keyOpen}
          onOpenChange={setKeyOpen}
          title="Create an organization access key"
          description="The key is bound to this organization and carries only the permissions you name."
          schema={accessKeyFormSchema}
          defaultValues={{ label: '', permissions: [] }}
          onSubmit={async (values) => {
            const minted = await mintKey.mutateAsync({
              orgId,
              data: { label: values.label, permissions: values.permissions },
            });
            setToken(minted.token);
          }}
          submitLabel="Generate"
          pending={mintKey.isPending}
          submitDisabled={authorization.isFetching || authorization.isError || !canIssueKey}
        >
          {(form) => (
            <AccessKeyFormFields
              form={form}
              availablePermissions={authorization.permissions}
              canIssue={canIssueKey}
              permissionsLoading={authorization.isFetching}
            />
          )}
        </FormDialog>
      )}

      <KeyRevealDialog open={!!token} onOpenChange={(v) => !v && setToken(null)} token={token} />

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
