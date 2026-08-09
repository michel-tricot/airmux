import { useQuery } from '@tanstack/react-query'
import { listDataPlanes } from '../api'
import { Badge, formatWhen, Page, QueryStatus, Table, Td } from '../ui'

export default function DataPlanes() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['data-planes'],
    queryFn: () => listDataPlanes(true),
    refetchInterval: 10000,
  })
  const instances = data ?? []

  return (
    <Page title="Data planes">
      <QueryStatus isLoading={isLoading} error={error} empty={instances.length === 0} />
      {instances.length > 0 && (
        <Table headers={['Instance', 'Org', 'Version', 'Bundle', 'Address', 'Status', 'First seen', 'Last seen']}>
          {instances.map((i) => (
            <tr key={i.instance_id} className="hover:bg-slate-900/50">
              <Td mono>{i.instance_id}</Td>
              <Td mono>{i.org_id ?? '-'}</Td>
              <Td mono>{i.version}</Td>
              <Td mono>{i.bundle_id ?? '-'}</Td>
              <Td mono>{i.address ?? '-'}</Td>
              <Td>
                <Badge tone={i.status === 'online' ? 'ok' : 'err'}>{i.status}</Badge>
              </Td>
              <Td>{formatWhen(i.first_seen)}</Td>
              <Td>{formatWhen(i.last_seen)}</Td>
            </tr>
          ))}
        </Table>
      )}
    </Page>
  )
}
