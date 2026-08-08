import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, approveCli, createPersonalOrg, getCliRequest, getEnrollment } from '../api'
import { Button, inputClass } from '../ui'

function detailsError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return 'no pending login with this code; check the code in your terminal or run airllm login again'
    if (error.status === 410) return 'this login request expired; run airllm login again'
    if (error.status === 409) return 'this login request was already approved'
  }
  return 'could not look up the login request'
}

function CreateOrgInline({ onCreated }: { onCreated: (orgId: string) => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const create = useMutation({
    mutationFn: () => createPersonalOrg({ name }),
    onSuccess: (org) => {
      queryClient.invalidateQueries({ queryKey: ['enrollment'] })
      queryClient.invalidateQueries({ queryKey: ['me'] })
      onCreated(org.id)
    },
  })
  return (
    <div className="space-y-2">
      <p className="text-sm text-slate-400">You are not in any organization yet. Create yours to continue</p>
      <div className="flex gap-2">
        <input
          className={`flex-1 ${inputClass}`}
          placeholder="organization name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Button disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
          Create
        </Button>
      </div>
      {create.error != null && <p className="text-sm text-red-400">could not create the organization</p>}
    </div>
  )
}

export default function CliApprove() {
  const [code, setCode] = useState(new URLSearchParams(window.location.search).get('code') ?? '')
  const [submitted, setSubmitted] = useState<string | null>(null)
  const [orgId, setOrgId] = useState('')

  const details = useQuery({
    queryKey: ['cli-request', submitted],
    queryFn: () => getCliRequest(submitted ?? ''),
    enabled: submitted !== null,
    retry: false,
  })
  const enrollment = useQuery({ queryKey: ['enrollment'], queryFn: getEnrollment, enabled: submitted !== null })
  const approve = useMutation({ mutationFn: () => approveCli({ user_code: submitted ?? '', org_id: orgId }) })

  const orgs = enrollment.data?.orgs ?? []
  const selected = orgId || (orgs[0]?.id ?? '')

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950">
      <div className="w-[28rem] space-y-5 rounded-xl border border-slate-800 bg-slate-900 p-8">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Authorize CLI login</h1>
          <p className="mt-1 text-sm text-slate-500">Only continue if you just ran airllm login yourself</p>
        </div>

        {approve.isSuccess ? (
          <p className="text-sm text-emerald-300">Approved. Return to your terminal, your login will complete in a few seconds</p>
        ) : submitted === null || details.error != null ? (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (code.trim()) setSubmitted(code.trim())
            }}
          >
            <input
              className={`w-full font-mono ${inputClass}`}
              placeholder="code from your terminal, e.g. XKCD-42AB"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoFocus
            />
            {submitted !== null && details.error != null && <p className="text-sm text-red-400">{detailsError(details.error)}</p>}
            <Button type="submit" disabled={!code.trim() || details.isFetching}>
              Look up request
            </Button>
          </form>
        ) : details.data == null ? (
          <p className="text-sm text-slate-500">Loading...</p>
        ) : (
          <div className="space-y-4">
            <div className="rounded-lg border border-slate-800 bg-slate-950/50 px-4 py-3 text-sm">
              <p className="text-slate-300">
                <span className="font-mono">{details.data.client_name}</span> is asking to log in
              </p>
              <p className="mt-1 text-slate-500">requested from {details.data.requester || 'an unknown address'}</p>
            </div>
            {orgs.length === 0 ? (
              <CreateOrgInline onCreated={setOrgId} />
            ) : (
              <div className="space-y-2">
                <p className="text-sm text-slate-400">The CLI will get a token for this organization</p>
                <select className={`w-full ${inputClass}`} value={selected} onChange={(e) => setOrgId(e.target.value)}>
                  {orgs.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {approve.error != null && <p className="text-sm text-red-400">approval failed; the request may have expired</p>}
            <Button disabled={!selected || approve.isPending} onClick={() => approve.mutate()}>
              Approve
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
