Reviewed against the repository on 2026-09-14. Replit notes apply to that deployment environment, not every local checkout.

- [Backend setup](backend-setup-quirks.md): current commands, Python configuration, taxonomy path, ports, and bootstrap authentication token
- [Orval Zod v4 import](orval-zod-v4.md): preserve the generated `zod/v4` import rewrite before type checking
- [Replit workflow host binding](replit-workflow-host-binding.md): current loopback binding and historical workflow-monitor behavior
- [Preview port routing](preview-port-routing.md): the Replit 20383-to-80 port mapping and its post-merge restoration
- [Replit DATABASE_URL and asyncpg](database-url-asyncpg.md): helper-local conversion between asyncpg and libpq URL parameters
- [Managed Postgres reset](managed-postgres-reset.md): existing Replit development reset behavior and its environment-specific scope
- [Browser verification](browser-e2e-harness.md): use the available browser backend against a real deployment; historical Nix setup is not a prerequisite
- [Zod Vitest interop](zod-vitest-interop.md): retain the namespace-import convention; the historical failure has not been revalidated
- [OpenAPI parameter descriptions](openapi-param-descriptions.md): explicit descriptions take precedence over centralized fallback descriptions
- [Bun lockfile validation](bun-lockfile-validation.md): validate with Bun's frozen install instead of a strict JSON parser
