import { useQuery } from '@tanstack/react-query'
import { listEvents } from '../api'
import { Badge, formatUsd, formatWhen, Page, QueryStatus, Table, Td } from '../ui'

export default function Events() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['events'],
    queryFn: () => listEvents(100),
    refetchInterval: 3000,
  })

  const events = data ?? []
  const totalCost = events.reduce((sum, e) => sum + e.cost_usd, 0)

  return (
    <Page
      title="Events"
      actions={events.length > 0 ? <span className="text-sm text-slate-400">last {events.length} requests, {formatUsd(totalCost)}</span> : undefined}
    >
      <QueryStatus isLoading={isLoading} error={error} empty={events.length === 0} />
      {events.length > 0 && (
        <Table headers={['When', 'Workspace', 'Key', 'Model', 'Status', 'In', 'Out', 'Cache r/w', 'Cost', 'Latency']}>
          {events.map((e) => (
            <tr key={e.event_id} className="hover:bg-slate-900/50">
              <Td>{formatWhen(e.occurred_at)}</Td>
              <Td mono>{e.workspace_id.slice(0, 8)}</Td>
              <Td mono>{e.key_id}</Td>
              <Td mono>
                {e.model_id}
                {e.stream && <span className="ml-1.5 text-slate-600">stream</span>}
              </Td>
              <Td>
                <Badge tone={e.status === 'ok' ? 'ok' : 'err'}>{e.status}</Badge>
              </Td>
              <Td mono>{e.input_tokens.toLocaleString()}</Td>
              <Td mono>{e.output_tokens.toLocaleString()}</Td>
              <Td mono>
                {e.cache_read_tokens.toLocaleString()}/{e.cache_write_tokens.toLocaleString()}
              </Td>
              <Td mono>{formatUsd(e.cost_usd)}</Td>
              <Td mono>{e.latency_ms}ms</Td>
            </tr>
          ))}
        </Table>
      )}
    </Page>
  )
}
