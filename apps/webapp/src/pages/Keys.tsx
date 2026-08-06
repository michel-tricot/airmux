import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createKey, listKeys, revokeKey } from '../api'
import { Badge, Button, formatWhen, Page, QueryStatus, Table, Td } from '../ui'

export default function Keys() {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({ queryKey: ['keys'], queryFn: listKeys })
  const [minted, setMinted] = useState<{ key_id: string; token: string } | null>(null)

  const create = useMutation({
    mutationFn: createKey,
    onSuccess: (result) => {
      setMinted(result)
      queryClient.invalidateQueries({ queryKey: ['keys'] })
    },
  })

  const revoke = useMutation({
    mutationFn: revokeKey,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['keys'] }),
  })

  const keys = data ?? []

  return (
    <Page title="Keys">
      <div className="mb-4 flex items-center gap-2">
        <Button disabled={create.isPending} onClick={() => create.mutate()}>
          Mint key
        </Button>
        {create.error && <span className="text-sm text-red-400">{create.error.message}</span>}
      </div>
      {minted && (
        <div className="mb-6 flex items-center gap-3 rounded-lg border border-emerald-800 bg-emerald-950/50 px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm text-emerald-300">
              Key <span className="font-mono">{minted.key_id}</span> minted. Copy the token now, it is not shown again
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
        <Table headers={['Key', 'Org', 'Owner', 'Status', 'Created', '']}>
          {keys.map((k) => (
            <tr key={k.id} className="hover:bg-slate-900/50">
              <Td mono>{k.id}</Td>
              <Td mono>{k.org_id}</Td>
              <Td mono>{k.user_id}</Td>
              <Td>
                <Badge tone={k.disabled ? 'err' : 'ok'}>{k.disabled ? 'revoked' : 'active'}</Badge>
              </Td>
              <Td>{formatWhen(k.created_at)}</Td>
              <Td>
                {!k.disabled && (
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
