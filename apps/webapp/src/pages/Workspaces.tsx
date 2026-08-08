import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createWorkspace, listWorkspaces } from '../api'
import { Button, formatWhen, inputClass, Page, QueryStatus, Table, Td } from '../ui'

export default function Workspaces() {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({ queryKey: ['workspaces'], queryFn: listWorkspaces })
  const [name, setName] = useState('')

  const create = useMutation({
    mutationFn: createWorkspace,
    onSuccess: () => {
      setName('')
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
  })

  const workspaces = data ?? []

  return (
    <Page title="Workspaces">
      <form
        className="mb-6 flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) create.mutate(name.trim())
        }}
      >
        <input className={inputClass} placeholder="name, e.g. staging" value={name} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" disabled={create.isPending || !name.trim()}>
          Create workspace
        </Button>
        {create.error && <span className="text-sm text-red-400">{create.error.message}</span>}
      </form>
      <QueryStatus isLoading={isLoading} error={error} empty={workspaces.length === 0} />
      {workspaces.length > 0 && (
        <Table headers={['Id', 'Name', 'Created']}>
          {workspaces.map((w) => (
            <tr key={w.id} className="hover:bg-slate-900/50">
              <Td mono>{w.id}</Td>
              <Td>{w.name}</Td>
              <Td>{formatWhen(w.created_at)}</Td>
            </tr>
          ))}
        </Table>
      )}
    </Page>
  )
}
