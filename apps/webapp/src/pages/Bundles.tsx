import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { compileBundle, listBundles } from '../api'
import { Button, formatWhen, Page, QueryStatus, Table, Td } from '../ui'

export default function Bundles() {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({ queryKey: ['bundles'], queryFn: listBundles })

  const compile = useMutation({
    mutationFn: compileBundle,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bundles'] }),
  })

  const bundles = data ?? []

  return (
    <Page title="Bundles">
      <div className="mb-6 flex items-center gap-2">
        <Button disabled={compile.isPending} onClick={() => compile.mutate()}>
          Compile bundle
        </Button>
        {compile.data && (
          <span className="text-sm text-emerald-400">
            compiled v{compile.data.version}
          </span>
        )}
        {compile.error && <span className="text-sm text-red-400">{compile.error.message}</span>}
      </div>
      <QueryStatus isLoading={isLoading} error={error} empty={bundles.length === 0} />
      {bundles.length > 0 && (
        <Table headers={['Org', 'Version', 'Bundle id', 'Issued', 'Expires', 'Signing key']}>
          {bundles.map((b) => (
            <tr key={b.id} className="hover:bg-slate-900/50">
              <Td mono>{b.org_id}</Td>
              <Td mono>v{b.version}</Td>
              <Td mono>{b.id}</Td>
              <Td>{formatWhen(b.issued_at)}</Td>
              <Td>{formatWhen(b.expires_at)}</Td>
              <Td mono>{b.signing_key_id}</Td>
            </tr>
          ))}
        </Table>
      )}
    </Page>
  )
}
