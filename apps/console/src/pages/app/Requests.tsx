import { useSearchParams } from 'wouter';
import { RequestsExplorer } from '@/components/shared/requests-explorer';
import { useAuthorization } from '@/features/permissions/hooks';
import { parseRequestFilters, setRequestFilter } from '@/features/reporting/request-filters';
import { telemetryAccess } from '@/features/telemetry/policy';
import { useRequiredOrgId } from '@/lib/session';

export default function Requests() {
  const orgId = useRequiredOrgId();
  const authorization = useAuthorization('org');
  const authorized = authorization.can(telemetryAccess.orgRequests);
  const [search, setSearch] = useSearchParams();
  const filters = parseRequestFilters(search, Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');

  return (
    <RequestsExplorer
      orgId={orgId}
      scope="organization"
      title="Organization Requests"
      description="Logical gateway requests, retries, accounting evidence, and exact export across all workspaces."
      filters={filters}
      authorized={authorized}
      onFilterChange={(name, value) => setSearch(setRequestFilter(search, name, value), { replace: true })}
    />
  );
}
