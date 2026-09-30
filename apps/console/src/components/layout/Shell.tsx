import { useLocation } from 'wouter';
import { Users } from 'lucide-react';
import { useSession } from '@/lib/session';
import { AirmuxBrand, ResponsiveShell } from '@/components/layout/responsive-shell';
import { ConsoleSidebar, ConsoleNavigationLink, ConsoleNavigationHeading } from '@/components/shared/console-sidebar';
import { useAuthorization } from '@/features/permissions/hooks';
import { instanceRoutes } from '@/pages/instance-routes';

export function Shell({ children }: { children: React.ReactNode }) {
  const [location] = useLocation();
  const { user } = useSession();
  const authorization = useAuthorization('instance');
  const navigation = instanceRoutes.flatMap((route) =>
    route.navigation && authorization.can(route.access) ? [{ path: route.path, ...route.navigation }] : [],
  );
  const roleLabel = user?.instance_role === 'owner' ? 'Owner' : user?.instance_role === 'auditor' ? 'Auditor' : 'Data plane';

  const sidebar = (close: () => void) => (
    <ConsoleSidebar
      homeHref="/instance"
      onNavigate={close}
      accountDescription={roleLabel}
      switchConsole={{ href: '/org', label: 'Workspace console', icon: Users }}
    >
      <nav aria-label="Instance navigation" className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
        <ConsoleNavigationHeading>Administration</ConsoleNavigationHeading>
        {navigation.map((item) => (
          <ConsoleNavigationLink
            key={item.path}
            href={item.path}
            label={item.label}
            icon={item.icon}
            active={location === item.path || (item.path !== '/instance' && location.startsWith(item.path))}
            onNavigate={close}
          />
        ))}
      </nav>
    </ConsoleSidebar>
  );

  return (
    <ResponsiveShell brand={<AirmuxBrand href="/instance" />} navigationLabel="Instance navigation" sidebar={sidebar}>
      {children}
    </ResponsiveShell>
  );
}
