import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  useCliAuthRequestDetails,
  useCliAuthApprove,
  useEnrollment,
  useCreatePersonalOrg,
  getCliAuthRequestDetailsQueryKey,
  getEnrollmentQueryKey,
  ApiError,
} from '@workspace/api-client-react';
import { Card, Button, Input, Label, Dropdown } from '@/components/ui/elements';
import { TerminalSquare, CheckCircle2 } from 'lucide-react';
import { formatRelative } from '@/lib/format';

function lookupError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return 'No pending login with this code. Check your terminal, or run airllm login again.';
    if (error.status === 410) return 'This login request expired. Run airllm login again.';
    if (error.status === 409) return 'This login request was already approved.';
  }
  return 'Could not look up the login request.';
}

export default function CliApprove() {
  const queryClient = useQueryClient();
  const [code, setCode] = useState(new URLSearchParams(window.location.search).get('code') ?? '');
  const [submitted, setSubmitted] = useState<string | null>(() => new URLSearchParams(window.location.search).get('code'));
  const [orgId, setOrgId] = useState('');
  const [name, setName] = useState('');

  const details = useCliAuthRequestDetails(
    { code: submitted ?? '' },
    { query: { queryKey: getCliAuthRequestDetailsQueryKey({ code: submitted ?? '' }), enabled: submitted !== null, retry: false } },
  );
  const { data: enrollment } = useEnrollment({ query: { queryKey: getEnrollmentQueryKey(), enabled: submitted !== null } });
  const approve = useCliAuthApprove();
  const createPersonalOrg = useCreatePersonalOrg({
    mutation: {
      onSuccess: (org) => {
        queryClient.invalidateQueries({ queryKey: getEnrollmentQueryKey() });
        setOrgId(org.id);
      },
    },
  });

  const orgs = enrollment?.orgs ?? [];
  const selected = orgId || orgs[0]?.id || '';

  return (
    <div className="min-h-[100dvh] flex items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-md p-8 shadow-xl border-border/50 space-y-6">
        <div className="flex flex-col items-center">
          <div className="w-12 h-12 rounded bg-primary text-primary-foreground flex items-center justify-center mb-4">
            <TerminalSquare className="w-6 h-6" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Authorize CLI login</h1>
          <p className="text-muted-foreground text-sm mt-1 text-center">Only continue if you just ran airllm login yourself.</p>
        </div>

        {approve.isSuccess ? (
          <div className="flex items-start gap-3 p-4 rounded-md bg-green-500/10 border border-green-500/20">
            <CheckCircle2 className="w-5 h-5 text-green-500 shrink-0 mt-0.5" />
            <p className="text-sm">Approved. Return to your terminal; the login completes within a few seconds.</p>
          </div>
        ) : submitted === null || details.error ? (
          <form
            className="space-y-4"
            onSubmit={e => { e.preventDefault(); if (code.trim()) setSubmitted(code.trim()); }}
          >
            <div className="space-y-2">
              <Label htmlFor="code">Code from your terminal</Label>
              <Input id="code" required value={code} className="font-mono" placeholder="ABCD-1234" onChange={e => setCode(e.target.value)} />
            </div>
            {details.error && <p className="text-sm text-destructive">{lookupError(details.error)}</p>}
            <Button type="submit" className="w-full">Look up request</Button>
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

            {orgs.length > 0 ? (
              <div className="space-y-2">
                <Label htmlFor="org">Organization the CLI will act in</Label>
                <Dropdown
                  aria-label="Organization"
                  value={selected}
                  onValueChange={setOrgId}
                  options={orgs.map(org => ({ value: org.id, label: org.name }))}
                />
              </div>
            ) : (
              <form className="space-y-2" onSubmit={e => { e.preventDefault(); createPersonalOrg.mutate({ data: { name } }); }}>
                <Label htmlFor="org-name">You are not in an organization yet. Create yours to continue.</Label>
                <div className="flex gap-2">
                  <Input id="org-name" required value={name} placeholder="organization name" onChange={e => setName(e.target.value)} />
                  <Button type="submit" disabled={createPersonalOrg.isPending}>Create</Button>
                </div>
              </form>
            )}

            {approve.error && <p className="text-sm text-destructive">Could not approve this request.</p>}

            <Button
              className="w-full"
              disabled={!selected || approve.isPending}
              onClick={() => approve.mutate({ data: { user_code: submitted, org_id: selected } })}
            >
              {approve.isPending ? 'Approving...' : 'Authorize'}
            </Button>
          </div>
        ) : (
          <p className="text-center text-muted-foreground font-mono text-sm">LOADING REQUEST...</p>
        )}
      </Card>
    </div>
  );
}
