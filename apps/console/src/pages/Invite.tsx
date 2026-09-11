import { useEffect, useState } from 'react';
import { useLocation } from 'wouter';
import { ApiError, usePreviewInvitation } from '@workspace/api-client-react';
import { Alert, AlertDescription, AlertTitle, Badge, Button, Card } from '@/components/ui/elements';
import { Building2, LogOut, Mail, Users } from 'lucide-react';
import Login from '@/pages/Login';
import { ErrorState, LoadingState } from '@/components/shared/states';
import { formatDate } from '@/lib/format';
import { useSession } from '@/lib/session';
import { useAcceptInvitationMutation } from '@/features/invitations/hooks';

function invitationToken(): string | null {
  return new URLSearchParams(window.location.hash.slice(1)).get('token');
}

export default function Invite() {
  const [token] = useState(invitationToken);
  const { user, setOrgId, logout } = useSession();
  const [, setLocation] = useLocation();
  const preview = usePreviewInvitation({ mutation: { meta: { silentError: true } } });
  const accept = useAcceptInvitationMutation();
  const { mutate } = preview;

  useEffect(() => {
    if (token) window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
  }, [token]);

  useEffect(() => {
    if (token) mutate({ data: { token } });
  }, [mutate, token]);

  if (!token) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30 p-4">
        <Card className="w-full max-w-lg">
          <ErrorState message="This invitation link is missing its secret. Ask the sender for a new link." />
        </Card>
      </div>
    );
  }

  if (preview.isPending || preview.isIdle) {
    return <LoadingState label="Loading invitation..." className="min-h-[100dvh] flex items-center justify-center bg-muted/30" />;
  }

  if (preview.isError || !preview.data) {
    const unavailable = preview.error instanceof ApiError && preview.error.status === 410;
    return (
      <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30 p-4">
        <Card className="w-full max-w-lg">
          <ErrorState
            message={unavailable ? 'This invitation has expired or was revoked. Ask the sender for a new link.' : 'This invitation link is invalid.'}
          />
        </Card>
      </div>
    );
  }

  const invitation = preview.data;
  const destination = invitation.workspace_name ? `${invitation.org_name} · ${invitation.workspace_name}` : invitation.org_name;

  if (!user) {
    return (
      <Login
        initialEmail={invitation.email}
        initialMode="choice"
        emailReadOnly
        invitationToken={token}
        heading={`Join ${invitation.org_name}`}
        description={`This invitation is for ${invitation.email} and grants access to ${destination}. Create a new account or sign in to an existing one.`}
      />
    );
  }

  const emailMatches = user.email.toLocaleLowerCase() === invitation.email.toLocaleLowerCase();

  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-lg p-8 space-y-6">
        <div className="space-y-2 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded bg-primary text-primary-foreground shadow-md">
            <Users className="h-6 w-6" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Join {invitation.org_name}</h1>
          <p className="text-sm text-muted-foreground">Review the access this invitation grants before accepting.</p>
        </div>

        <div className="space-y-3 rounded border border-border bg-muted/30 p-4 text-sm">
          <div className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-2 text-muted-foreground">
              <Mail className="h-4 w-4" /> Email
            </span>
            <span className="font-medium">{invitation.email}</span>
          </div>
          <div className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-2 text-muted-foreground">
              <Building2 className="h-4 w-4" /> Organization
            </span>
            <span className="flex items-center gap-2">
              {invitation.org_name} <Badge variant="outline">{invitation.org_role}</Badge>
            </span>
          </div>
          {invitation.workspace_name && (
            <div className="flex items-center justify-between gap-4">
              <span className="text-muted-foreground">Workspace</span>
              <span className="flex items-center gap-2">
                {invitation.workspace_name} <Badge variant="outline">{invitation.workspace_role}</Badge>
              </span>
            </div>
          )}
          <div className="flex items-center justify-between gap-4">
            <span className="text-muted-foreground">Expires</span>
            <span>{formatDate(invitation.expires_at)}</span>
          </div>
        </div>

        {!emailMatches ? (
          <Alert variant="destructive">
            <div>
              <AlertTitle>Different account signed in</AlertTitle>
              <AlertDescription>
                This invitation is for {invitation.email}, but you are signed in as {user.email}.
              </AlertDescription>
            </div>
          </Alert>
        ) : null}

        {accept.isError && (
          <Alert variant="destructive">
            <div>
              <AlertTitle>Couldn’t accept invitation</AlertTitle>
              <AlertDescription>
                {accept.error instanceof ApiError && accept.error.status === 410
                  ? 'This invitation is no longer available.'
                  : 'Please try again or ask the sender for a new link.'}
              </AlertDescription>
            </div>
          </Alert>
        )}

        <div className="flex justify-end gap-2">
          {!emailMatches ? (
            <Button variant="outline" onClick={logout}>
              <LogOut className="h-4 w-4" /> Sign in with another account
            </Button>
          ) : (
            <Button
              disabled={accept.isPending}
              onClick={async () => {
                const accepted = await accept.mutateAsync({ data: { token } });
                setOrgId(accepted.org_id);
                setLocation(accepted.workspace_id ? `/org/workspaces/${accepted.workspace_id}` : '/org');
              }}
            >
              {accept.isPending ? 'Accepting...' : 'Accept invitation'}
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
}
