---
name: Replit DATABASE_URL and asyncpg
description: Replit's managed DATABASE_URL may use libpq query parameters that need helper-only normalization.
---

Replit's managed `DATABASE_URL` is the single database source of truth, but its PostgreSQL URL can include `sslmode`; the Replit backend helper normalizes that option to `ssl` for the application and back to `sslmode` for libpq tools.

**Why:** Passing the managed URL directly through SQLAlchemy caused the control plane to fail at startup with an unsupported `sslmode` keyword. This is an environment-specific concern and should not leak into generic platform configuration.

**How to apply:** Keep Replit helpers and docs on `DATABASE_URL` only. Normalize driver-specific URL parameters inside the Replit helper, while keeping application configuration generic.