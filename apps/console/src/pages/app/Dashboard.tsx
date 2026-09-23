import { UsageReporting } from '@/components/shared/usage-reporting';
import { PageHeader, PageShell } from '@/components/shared/page-shell';
import { useAuthorization } from '@/features/permissions/hooks';
import { telemetryAccess } from '@/features/telemetry/policy';

export default function AppDashboard() {
  const authorization = useAuthorization('org');
  if (authorization.can(telemetryAccess.orgUsage)) return <UsageReporting />;
  return (
    <PageShell>
      <PageHeader title="Organization Overview" description="Choose a section from the sidebar." />
    </PageShell>
  );
}
