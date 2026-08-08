import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { createKey, listKeys, listWorkspaces, revokeKey } from '../api'
import { Badge, Button, formatWhen, inputClass, Page, QueryStatus, Table, Td } from '../ui'

export default function Keys() {
  const queryClient = useQueryClient()
  const workspacesQuery = useQuery({ queryKey: ['workspaces'], queryFn: listWorkspaces })
  const workspaces = workspacesQuery.data ?? []
  const [selected, setSelected] = useState<string | null>(null)
  const workspaceId = selected && workspaces.some((w) => w.id === selected) ? selected : (workspaces[0]?.id ?? null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['keys', workspaceId],
    queryFn: () => listKeys(workspaceId!),
    enabled: !!workspaceId,
  })
  const [minted, setMinted] = useState<{ id: string; token: string } | null>(null)
  const [label, setLabel] = useState('')

  const create = useMutation({
    mutationFn: () => createKey(workspaceId!, label),
    onSuccess: (result) => {
      setMinted(result)
      setLabel('')
      queryClient.invalidateQueries({ queryKey: ['keys', workspaceId] })
    },
  })

  const revoke = useMutation({
    mutationFn: (keyId: string) => revokeKey(workspaceId!, keyId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['keys', workspaceId] }),
  })

  const keys = data ?? []

  if (workspacesQuery.isSuccess && workspaces.length === 0) {
    return (
      <Page title="Keys">
        <p className="text-sm text-slate-400">
          Keys live in a workspace and this org has none yet.{' '}
          <Link to="/workspaces" className="text-indigo-400 hover:text-indigo-300">
            Create a workspace
          </Link>{' '}
          first.
        </p>
      </Page>
    )
  }

  return (
    <Page title="Keys">
      <div className="mb-4 flex items-center gap-2">
        <select className={inputClass} value={workspaceId ?? ''} onChange={(e) => setSelected(e.target.value)}>
          {workspaces.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
        <input
          className={inputClass}
          placeholder="label, e.g. staging"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
        <Button disabled={!label.trim() || !workspaceId || create.isPending} onClick={() => create.mutate()}>
          Mint key
        </Button>
        {create.error && <span className="text-sm text-red-400">{create.error.message}</span>}
      </div>
      {minted && (
        <div className="mb-6 flex items-center gap-3 rounded-lg border border-emerald-800 bg-emerald-950/50 px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm text-emerald-300">
              Key <span className="font-mono">{minted.id}</span> minted. Copy the token now, it is not shown again
            </p>
            <p className="mt-1 truncate font-mono text-xs text-emerald-500">{minted.token}</p>
          </div>
          <Button onClick={() => navigator.clipboard.writeText(minted.token)}>Copy</Button>
          <button
            type="button"
            className="rounded-md px-3 py-1.5 text-sm text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            onClick={() => setMinted(null)}
          >
            Dismiss
          </button>
        </div>
      )}
      <QueryStatus isLoading={isLoading} error={error} empty={keys.length === 0} />
      {keys.length > 0 && (
        <Table headers={['Key', 'Label', 'Owner', 'Status', 'Created', '']}>
          {keys.map((k) => (
            <tr key={k.id} className="hover:bg-slate-900/50">
              <Td mono>{k.id}</Td>
              <Td>{k.label}</Td>
              <Td mono>{k.user_id}</Td>
              <Td>
                <Badge tone={k.revoked ? 'err' : 'ok'}>{k.revoked ? 'revoked' : 'active'}</Badge>
              </Td>
              <Td>{formatWhen(k.created_at)}</Td>
              <Td>
                {!k.revoked && (
                  <Button danger disabled={revoke.isPending} onClick={() => revoke.mutate(k.id)}>
                    Revoke
                  </Button>
                )}
              </Td>
            </tr>
          ))}
        </Table>
      )}
    </Page>
  )
}
