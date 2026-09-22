import { useSearchParams } from 'wouter';
import { SpendingOverview } from '@/components/shared/spending-overview';
import { useAuthorization } from '@/features/permissions/hooks';
import { orgOverviewParams, parseOverviewFilters, setOverviewFilter } from '@/features/reporting/filters';
import { useOrgOverviewReport } from '@/features/reporting/hooks';
import { telemetryAccess } from '@/features/telemetry/policy';
import { useRequiredOrgId } from '@/lib/session';

export default function AppDashboard() {
  const orgId = useRequiredOrgId();
  const authorization = useAuthorization('org');
  const authorized = authorization.can(telemetryAccess.orgOverview);
  const [search, setSearch] = useSearchParams();
  const filters = parseOverviewFilters(search, Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');
  const report = useOrgOverviewReport(orgId, orgOverviewParams(filters), { enabled: authorized });

  return (
    <SpendingOverview
      title="Organization Overview"
      description="Gateway-observed estimated spending and usage across all workspaces."
      scope="organization"
      filters={filters}
      onFilterChange={(name, value) => setSearch(setOverviewFilter(search, name, value), { replace: true })}
      query={report}
      authorized={authorized}
    />
  );
}
