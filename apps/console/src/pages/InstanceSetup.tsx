import { useState } from 'react';
import { Link, useLocation } from 'wouter';
import { CheckCircle2 } from 'lucide-react';
import { AddProviderCredentialDialog } from '@/components/shared/provider-credential-dialog';
import { CreateOrganizationDialog } from '@/components/shared/create-organization-dialog';
import { PageHeader, PageShell, SectionHeader } from '@/components/shared/page-shell';
import { ErrorState, LoadingState } from '@/components/shared/states';
import { Alert, AlertDescription, AlertTitle, Badge, Button, Card } from '@/components/ui/elements';
import { useAddInstanceCredentialMutation, useInstanceProviderCredentials, useInstanceProviders } from '@/features/credentials/hooks';
import { useCreateOrgMutation, useOrgSummary } from '@/features/orgs/hooks';

export default function InstanceSetup() {
  const credentialsQuery = useInstanceProviderCredentials();
  const orgsQuery = useOrgSummary();
  const providersQuery = useInstanceProviders();
  const addCredential = useAddInstanceCredentialMutation();
  const createOrg = useCreateOrgMutation();
  const [addOpen, setAddOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [, navigate] = useLocation();
  const queries = [credentialsQuery, orgsQuery, providersQuery];
  const failedQuery = queries.find((query) => query.isError);

  if (queries.some((query) => query.isLoading)) return <LoadingState label="Loading setup progress..." />;
  if (failedQuery) return <ErrorState error={failedQuery.error} resource="setup progress" onRetry={() => failedQuery.refetch()} />;
  if (!credentialsQuery.data || !orgsQuery.data || !providersQuery.data)
    return <ErrorState message="Setup progress is unavailable. Reload to try again." />;

  const keysSaved = credentialsQuery.data.filter((credential) => credential.enabled).length;
  const hasKeys = keysSaved > 0;
  const hasOrg = orgsQuery.data.total > 0;
  const complete = hasKeys && hasOrg;
  const providers = providersQuery.data.providers;

  return (
    <PageShell className="max-w-3xl space-y-8">
      <PageHeader title="Set up your instance" description="Connect a provider and create a home for your team." />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p role="status" className="text-sm font-medium">
          {Number(hasKeys) + Number(hasOrg)} of 2 steps complete
        </p>
        <Badge variant="success">Admin account created</Badge>
      </div>
      <ol aria-label="Setup steps" className="space-y-4">
        <li>
          <Card className="space-y-5 p-6">
            <SectionHeader
              title="1. Add provider keys"
              description="Instance keys are available to every organization. Add one or more provider accounts."
              actions={<Badge variant={hasKeys ? 'success' : 'outline'}>{hasKeys ? 'Complete' : 'To do'}</Badge>}
            />
            {hasKeys && (
              <p className="text-sm text-success">
                {keysSaved} instance provider {keysSaved === 1 ? 'key' : 'keys'} saved
              </p>
            )}
            {providers.length === 0 && (
              <Alert>
                <div>
                  <AlertTitle>No providers available</AlertTitle>
                  <AlertDescription>Ask your instance operator to load the provider catalog, then reload this page.</AlertDescription>
                </div>
              </Alert>
            )}
            <Button variant={hasKeys ? 'outline' : 'default'} disabled={providers.length === 0} onClick={() => setAddOpen(true)}>
              {hasKeys ? 'Add another provider key' : 'Add provider key'}
            </Button>
            <p className="text-xs text-muted-foreground">Saving a key does not test it. Its status updates after an inference request.</p>
          </Card>
        </li>
        <li>
          <Card className="space-y-5 p-6">
            <SectionHeader
              title="2. Create an organization"
              description="Organizations group your workspaces, access, and usage."
              actions={<Badge variant={hasOrg ? 'success' : 'outline'}>{hasOrg ? 'Complete' : 'To do'}</Badge>}
            />
            {hasOrg ? (
              <p className="text-sm text-success">Your first organization is ready</p>
            ) : (
              <Button onClick={() => setCreateOpen(true)}>Create organization</Button>
            )}
          </Card>
        </li>
      </ol>
      {complete && (
        <Alert variant="success" role="status">
          <CheckCircle2 />
          <div>
            <AlertTitle>Your instance setup is complete</AlertTitle>
            <AlertDescription>Continue to the instance console to manage your organization and create workspaces.</AlertDescription>
          </div>
        </Alert>
      )}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <Button asChild variant="ghost">
          <Link href="/instance">Finish later</Link>
        </Button>
        <Button disabled={!complete} onClick={() => navigate('/instance')}>
          Finish setup
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        Each completed step is saved. You can sign out and return to Setup in the instance sidebar to continue.
      </p>
      <AddProviderCredentialDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        providers={providers}
        onSubmit={(values) => addCredential.mutateAsync({ data: values })}
        pending={addCredential.isPending}
      />
      <CreateOrganizationDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSubmit={(values) => createOrg.mutateAsync({ data: values })}
        pending={createOrg.isPending}
      />
    </PageShell>
  );
}
