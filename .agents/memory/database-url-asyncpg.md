---
name: Replit DATABASE_URL and asyncpg
description: Replit's managed DATABASE_URL may use libpq query parameters that need asyncpg normalization.
---

Replit's managed `DATABASE_URL` is the single database source of truth, but its PostgreSQL URL can include `sslmode`; asyncpg needs that option normalized to `ssl` before connection.

**Why:** Passing the managed URL directly through SQLAlchemy caused the control plane to fail at startup with an unsupported `sslmode` keyword.

**How to apply:** Keep Replit helpers and docs on `DATABASE_URL` only, and preserve TLS-related query options while normalizing driver-specific URL parameters in the control-plane config boundary.