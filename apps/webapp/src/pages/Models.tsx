import { useQuery } from '@tanstack/react-query'
import { getTaxonomy } from '../api'
import { Page, QueryStatus, Table, Td } from '../ui'

export default function Models() {
  const { data, isLoading, error } = useQuery({ queryKey: ['taxonomy'], queryFn: getTaxonomy })
  const models = data?.models ?? []

  return (
    <Page title="Models">
      <QueryStatus isLoading={isLoading} error={error} empty={models.length === 0} />
      {models.length > 0 && (
        <Table headers={['Id', 'Provider', 'Upstream', 'In $/Mtok', 'Out $/Mtok', 'Context', 'Max out', 'Capabilities']}>
          {models.map((m) => (
            <tr key={m.id} className="hover:bg-slate-900/50">
              <Td mono>{m.id}</Td>
              <Td mono>{m.provider_id}</Td>
              <Td mono>{m.upstream_model}</Td>
              <Td mono>{m.input_price_per_mtok}</Td>
              <Td mono>{m.output_price_per_mtok}</Td>
              <Td mono>{m.context_window.toLocaleString()}</Td>
              <Td mono>{m.max_output_tokens?.toLocaleString() ?? '-'}</Td>
              <Td>
                <span className="flex flex-wrap gap-1">
                  {m.capabilities.map((c) => (
                    <span key={c} className="inline-flex rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-300 ring-1 ring-slate-700">
                      {c}
                    </span>
                  ))}
                </span>
              </Td>
            </tr>
          ))}
        </Table>
      )}
    </Page>
  )
}
