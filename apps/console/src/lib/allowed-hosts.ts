const LOCAL_HOSTS = ['localhost', '127.0.0.1'];

export function resolveAllowedHosts(configuredHosts: string | undefined, isReplit: boolean): string[] | true {
  if (configuredHosts === undefined && isReplit) return true;
  return (configuredHosts ?? LOCAL_HOSTS.join(','))
    .split(',')
    .map((host) => host.trim())
    .filter(Boolean);
}
