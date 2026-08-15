import { useState } from 'react';
import {
  useCliAuthRequestDetails,
  useCliAuthApprove,
  useEnrollment,
  getCliAuthRequestDetailsQueryKey,
  getEnrollmentQueryKey,
  ApiError,
} from '@workspace/api-client-react';
import { useCreatePersonalOrgMutation } from '@/features/orgs/hooks';
import { Alert, AlertDescription, Card, Button, Input, Label, Dropdown } from '@/components/ui/elements';
import { TerminalSquare, CheckCircle2 } from 'lucide-react';
import { formatRelative } from '@/lib/format';
import { ErrorState, LoadingState } from '@/components/shared/states';

function lookupError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return 'No pending login with this code. Check your terminal, or run airllm login again.';
    if (error.status === 410) return 'This login request expired. Run airllm login again.';
    if (error.status === 409) return 'This login request was already approved.';
  }
  return 'Could not look up the login request.';
}

export default function CliApprove() {
  const [code, setCode] = useState(new URLSearchParams(window.location.search).get('code') ?? '');
  const [submitted, setSubmitted] = useState<string | null>(() => new URLSearchParams(window.location.search).get('code'));
  const [orgId, setOrgId] = useState('');
  const [name, setName] = useState('');

  const details = useCliAuthRequestDetails(
    { code: submitted ?? '' },
    { query: { queryKey: getCliAuthRequestDetailsQueryKey({ code: submitted ?? '' }), enabled: submitted !== null, retry: false } },
  );
  const enrollment = useEnrollment({ query: { queryKey: getEnrollmentQueryKey(), enabled: submitted !== null, retry: false } });
  const approve = useCliAuthApprove();
  const createPersonalOrg = useCreatePersonalOrgMutation();
  const submitPersonalOrg = (name: string) => createPersonalOrg.mutate({ data: { name } }, { onSuccess: (org) => setOrgId(org.id) });

  const orgs = enrollment.data?.orgs ?? [];
  const selected = orgId || orgs[0]?.id || '';

  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-md p-8 shadow-xl border-border/50 space-y-6">
        <div className="flex flex-col items-center">
          <div className="w-12 h-12 rounded bg-primary text-primary-foreground flex items-center justify-center mb-4">
            <TerminalSquare className="w-6 h-6" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Authorize CLI login</h1>
          <p className="text-muted-foreground text-sm mt-1 text-center">
            Continue only if you just ran <code>airllm login</code>.
          </p>
        </div>

        {approve.isSuccess ? (
          <Alert role="status" variant="success">
            <CheckCircle2 />
            <AlertDescription>Approved. Return to your terminal; the login completes within a few seconds.</AlertDescription>
          </Alert>
        ) : submitted === null || details.error ? (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (code.trim()) setSubmitted(code.trim());
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="code">Code from your terminal</Label>
              <Input id="code" required value={code} className="font-mono" placeholder="ABCD-1234" onChange={(e) => setCode(e.target.value)} />
            </div>
            {details.error && (
              <p role="alert" className="text-sm text-destructive">
                {lookupError(details.error)}
              </p>
            )}
            <Button type="submit" className="w-full">
              Look up request
            </Button>
          </form>
        ) : details.data ? (
          <div className="space-y-4">
            <dl className="text-sm space-y-2">
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Client</dt>
                <dd className="font-medium">{details.data.client_name}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Requested from</dt>
                <dd className="font-mono text-xs">{details.data.requester || 'unknown'}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Expires</dt>
                <dd>{formatRelative(details.data.expires_at)}</dd>
              </div>
            </dl>

            {enrollment.isLoading ? (
              <LoadingState label="Loading organizations..." />
            ) : enrollment.isError ? (
              <ErrorState message="Could not load your organizations. Try again." onRetry={() => enrollment.refetch()} />
            ) : orgs.length > 0 ? (
              <div className="space-y-2">
                <Label htmlFor="org">Organization for CLI access</Label>
                <Dropdown
                  aria-label="Organization"
                  value={selected}
                  onValueChange={setOrgId}
                  options={orgs.map((org) => ({ value: org.id, label: org.name }))}
                />
              </div>
            ) : (
              <form
                className="space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  submitPersonalOrg(name);
                }}
              >
                <Label htmlFor="org-name">You are not in an organization yet. Create yours to continue.</Label>
                <div className="flex gap-2">
                  <Input id="org-name" required value={name} placeholder="organization name" onChange={(e) => setName(e.target.value)} />
                  <Button type="submit" disabled={createPersonalOrg.isPending}>
                    Create
                  </Button>
                </div>
              </form>
            )}

            {approve.error && (
              <p role="alert" className="text-sm text-destructive">
                Could not approve this request.
              </p>
            )}

            <Button
              className="w-full"
              disabled={!selected || approve.isPending || enrollment.isLoading || enrollment.isError}
              onClick={() => approve.mutate({ data: { user_code: submitted, org_id: selected } })}
            >
              {approve.isPending ? 'Approving...' : 'Authorize'}
            </Button>
          </div>
        ) : (
          <LoadingState label="Loading request..." />
        )}
      </Card>
    </div>
  );
}
