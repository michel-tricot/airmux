import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useEnrollment, useCreatePersonalOrg, getEnrollmentQueryKey } from '@workspace/api-client-react';
import { useSession } from '@/lib/session';
import { Card, Button, Input, Label } from '@/components/ui/elements';
import { Building2 } from 'lucide-react';

export default function AppOrgPicker() {
  const { setOrgId, logout } = useSession();
  const queryClient = useQueryClient();
  const { data: enrollment, isLoading } = useEnrollment();
  const [name, setName] = useState('');

  const orgs = enrollment?.orgs;
  const single = orgs?.length === 1 ? orgs[0].id : null;

  useEffect(() => {
    if (single) setOrgId(single);
  }, [single, setOrgId]);

  const createPersonalOrg = useCreatePersonalOrg({
    mutation: {
      onSuccess: (org) => {
        queryClient.invalidateQueries({ queryKey: getEnrollmentQueryKey() });
        setOrgId(org.id);
      },
    },
  });

  if (isLoading || single) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30">
        <div className="text-muted-foreground font-mono text-sm">LOADING ORGANIZATIONS...</div>
      </div>
    );
  }

  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-lg p-8 shadow-xl border-border/50">
        <h1 className="text-2xl font-bold tracking-tight mb-2">Select Organization</h1>
        <p className="text-muted-foreground text-sm mb-6">Choose an organization to continue.</p>

        <div className="space-y-3 mb-8">
          {orgs?.map(org => (
            <Button
              key={org.id}
              variant="outline"
              className="w-full justify-start h-16 text-left hover:border-primary hover:bg-primary/5 group"
              onClick={() => setOrgId(org.id)}
            >
              <div className="w-8 h-8 rounded bg-primary/10 flex items-center justify-center mr-4 group-hover:bg-primary/20 transition-colors">
                <Building2 className="w-4 h-4 text-primary" />
              </div>
              <div className="flex-1">
                <div className="font-medium text-base">{org.name}</div>
                <div className="text-xs text-muted-foreground font-mono">
                  {org.id}{org.id === enrollment?.personal_org_id ? ' • PERSONAL' : ''}
                </div>
              </div>
            </Button>
          ))}
          {orgs?.length === 0 && (
            <div className="text-center p-8 border border-dashed rounded-md text-muted-foreground">
              You don't belong to any organizations yet.
            </div>
          )}
        </div>

        {enrollment && enrollment.personal_org_id === null && (
          <form
            onSubmit={e => { e.preventDefault(); createPersonalOrg.mutate({ data: { name } }); }}
            className="space-y-2 border-t border-border pt-6 mb-6"
          >
            <Label htmlFor="personal-org">Create your personal organization</Label>
            <div className="flex gap-2">
              <Input id="personal-org" required value={name} placeholder="Jane's org" onChange={e => setName(e.target.value)} />
              <Button type="submit" disabled={createPersonalOrg.isPending}>Create</Button>
            </div>
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
