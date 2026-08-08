import { useListUserOrganizations, getListUserOrganizationsQueryKey } from '@workspace/api-client-react';
import { useSession } from '@/lib/session';
import { Card, Button } from '@/components/ui/elements';
import { Building2 } from 'lucide-react';
import { useEffect } from 'react';

export default function AppOrgPicker() {
  const { userId, setOrgId, logout } = useSession();
  const { data: orgs, isLoading } = useListUserOrganizations(userId!, { query: { enabled: !!userId, queryKey: getListUserOrganizationsQueryKey(userId!) }});

  useEffect(() => {
    if (orgs && orgs.length === 1) {
      setOrgId(orgs[0].orgId);
    }
  }, [orgs, setOrgId]);

  if (isLoading || (orgs && orgs.length === 1)) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30">
        <div className="text-muted-foreground font-mono text-sm">Loading workspace...</div>
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
              key={org.orgId} 
              variant="outline" 
              className="w-full justify-start h-16 text-left hover:border-primary hover:bg-primary/5 group"
              onClick={() => setOrgId(org.orgId)}
            >
              <div className="w-8 h-8 rounded bg-primary/10 flex items-center justify-center mr-4 group-hover:bg-primary/20 transition-colors">
                <Building2 className="w-4 h-4 text-primary" />
              </div>
              <div className="flex-1">
                <div className="font-medium text-base">{org.orgName}</div>
                <div className="text-xs text-muted-foreground font-mono">{org.orgSlug} • {org.role.toUpperCase()}</div>
              </div>
            </Button>
          ))}
          {orgs?.length === 0 && (
            <div className="text-center p-8 border border-dashed rounded-md text-muted-foreground">
              You don't belong to any organizations.
            </div>
          )}
        </div>

        <Button variant="ghost" className="w-full text-muted-foreground hover:text-foreground" onClick={logout}>Cancel & Sign out</Button>
      </Card>
    </div>
  );
}
