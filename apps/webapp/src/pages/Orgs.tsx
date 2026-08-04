import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createOrg, listOrgs } from '../api'
import { Button, formatWhen, inputClass, Page, QueryStatus, Table, Td } from '../ui'

export default function Orgs() {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({ queryKey: ['orgs'], queryFn: listOrgs })
  const [id, setId] = useState('')
  const [name, setName] = useState('')

  const create = useMutation({
    mutationFn: createOrg,
    onSuccess: () => {
      setId('')
      setName('')
      queryClient.invalidateQueries({ queryKey: ['orgs'] })
    },
  })

  const orgs = data ?? []

  return (
    <Page title="Orgs">
      <form
        className="mb-6 flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (id.trim()) create.mutate({ id: id.trim(), name: name.trim() })
        }}
      >
        <input className={inputClass} placeholder="org id, e.g. org-dev" value={id} onChange={(e) => setId(e.target.value)} />
        <input className={inputClass} placeholder="display name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" disabled={create.isPending || !id.trim()}>
          Create org
        </Button>
        {create.error && <span className="text-sm text-red-400">{create.error.message}</span>}
      </form>
      <QueryStatus isLoading={isLoading} error={error} empty={orgs.length === 0} />
      {orgs.length > 0 && (
        <Table headers={['Id', 'Name', 'Created']}>
          {orgs.map((o) => (
            <tr key={o.id} className="hover:bg-slate-900/50">
              <Td mono>{o.id}</Td>
              <Td>{o.name}</Td>
              <Td>{formatWhen(o.created_at)}</Td>
            </tr>
          ))}
        </Table>
      )}
    </Page>
  )
}
