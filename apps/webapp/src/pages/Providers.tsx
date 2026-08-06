import { useQuery } from '@tanstack/react-query'
import { getTaxonomy } from '../api'
import { Page, QueryStatus, Table, Td } from '../ui'

export default function Providers() {
  const { data, isLoading, error } = useQuery({ queryKey: ['taxonomy'], queryFn: getTaxonomy })
  const providers = data?.providers ?? []

  return (
    <Page title="Providers">
      <QueryStatus isLoading={isLoading} error={error} empty={providers.length === 0} />
      {providers.length > 0 && (
        <Table headers={['Id', 'Kind', 'Base URL', 'Credential', 'Cache r/w multipliers']}>
          {providers.map((p) => (
            <tr key={p.id} className="hover:bg-slate-900/50">
              <Td mono>{p.id}</Td>
              <Td>{p.kind}</Td>
              <Td mono>{p.base_url}</Td>
              <Td mono>{p.credential_ref}</Td>
              <Td mono>
                {p.cache_read_multiplier}/{p.cache_write_multiplier}
              </Td>
            </tr>
          ))}
        </Table>
      )}
    </Page>
  )
}
