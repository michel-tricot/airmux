import { useEffect } from 'react';
import { useLocation } from 'wouter';
import * as z from 'zod';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { getEnrollmentQueryKey, useEnrollment } from '@workspace/api-client-react';
import { useCreatePersonalOrgMutation } from '@/features/orgs/hooks';
import { useSession } from '@/lib/session';
import { Badge, Card, Button, Input, Label } from '@/components/ui/elements';
import { Building2, Mail } from 'lucide-react';
import { EmptyState, ErrorState, LoadingState } from '@/components/shared/states';
import { formatDate } from '@/lib/format';

const personalOrgSchema = z.object({ name: z.string().min(1, 'Name is required') });

export default function AppOrgPicker() {
  const { setOrgId, logout } = useSession();
  const [, setLocation] = useLocation();
  const pickOrg = (id: string) => {
    setOrgId(id);
    setLocation('/org');
  };
  const enrollment = useEnrollment({ query: { queryKey: getEnrollmentQueryKey(), retry: false } });
  const form = useForm<z.infer<typeof personalOrgSchema>>({
    resolver: zodResolver(personalOrgSchema),
    defaultValues: { name: '' },
  });

  const orgs = enrollment.data?.orgs;
  const pendingInvitations = enrollment.data?.pending_invitations ?? [];
  const single = orgs?.length === 1 ? orgs[0].id : null;

  useEffect(() => {
    if (single) {
      setOrgId(single);
      setLocation('/org', { replace: true });
    }
  }, [single, setOrgId, setLocation]);

  const createPersonalOrg = useCreatePersonalOrgMutation();
  const submitPersonalOrg = form.handleSubmit(async (values) => {
    const org = await createPersonalOrg.mutateAsync({ data: values }).catch(() => null);
    if (org) pickOrg(org.id);
  });

  if (enrollment.isLoading || single) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30">
        <LoadingState label="Loading organizations..." />
      </div>
    );
  }

  if (enrollment.isError || !enrollment.data) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30 p-4">
        <ErrorState message="Could not load your organizations. Try again." onRetry={() => enrollment.refetch()} />
      </div>
    );
  }

  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-lg p-8 shadow-xl shadow-black/40 border-border/50">
        <h1 className="text-xl font-mono font-bold tracking-widest uppercase mb-2">Select Organization</h1>
        <p className="text-muted-foreground text-sm mb-6">Choose an organization to continue.</p>

        {pendingInvitations.length > 0 && (
          <section aria-labelledby="pending-invitations" className="mb-8 space-y-3">
            <div>
              <h2 id="pending-invitations" className="font-mono text-sm font-bold uppercase tracking-wider">
                Pending invitations
              </h2>
              <p className="mt-1 text-xs text-muted-foreground">Open the invitation link you received to accept access.</p>
            </div>
            {pendingInvitations.map((invitation) => (
              <div key={invitation.org_id} className="rounded border border-primary/30 bg-primary/5 p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex min-w-0 items-start gap-3">
                    <Mail className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                    <div className="min-w-0">
                      <p className="font-medium">{invitation.org_name}</p>
                      {invitation.workspace_name && <p className="text-sm text-muted-foreground">{invitation.workspace_name}</p>}
                    </div>
                  </div>
                  <Badge variant="outline">
                    {invitation.org_role}
                    {invitation.workspace_role ? ` · ${invitation.workspace_role}` : ''}
                  </Badge>
                </div>
                <p className="mt-3 text-xs text-muted-foreground">Expires {formatDate(invitation.expires_at)}</p>
              </div>
            ))}
          </section>
        )}

        <div className="space-y-3 mb-8">
          {orgs?.map((org) => (
            <Button
              key={org.id}
              variant="outline"
              className="w-full justify-start gap-4 h-16 text-left hover:border-primary/50 hover:bg-primary/10 group"
              onClick={() => pickOrg(org.id)}
            >
              <div className="w-8 h-8 rounded bg-primary/10 flex items-center justify-center group-hover:bg-primary/20 transition-colors">
                <Building2 className="w-4 h-4 text-primary" />
              </div>
              <div className="flex-1">
                <div className="font-medium text-base tracking-tight">{org.name}</div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground/70 font-mono mt-1">
                  {org.id}
                  {org.id === enrollment.data.personal_org_id ? ' • PERSONAL' : ''}
                </div>
              </div>
            </Button>
          ))}
          {orgs?.length === 0 && (
            <EmptyState className="rounded-md border border-dashed border-border">You don't belong to any organizations yet.</EmptyState>
          )}
        </div>

        {enrollment.data.personal_org_id === null && (
          <form onSubmit={submitPersonalOrg} className="space-y-2 border-t border-border pt-6 mb-6">
            <Label htmlFor="personal-org">Create your personal organization</Label>
            <div className="flex gap-2">
              <Input id="personal-org" placeholder="Jane's org" {...form.register('name')} />
              <Button type="submit" disabled={createPersonalOrg.isPending}>
                Create
              </Button>
            </div>
            {form.formState.errors.name && <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>}
            <p className="text-xs text-muted-foreground">Every account may found one; further orgs are provisioned by an admin.</p>
          </form>
        )}

        <Button variant="ghost" className="w-full text-muted-foreground hover:text-foreground" onClick={logout}>
          Sign out
        </Button>
      </Card>
    </div>
  );
}
