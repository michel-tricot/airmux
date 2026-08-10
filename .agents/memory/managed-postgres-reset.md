---
name: Managed Postgres reset
description: How to actually reset the Replit development database; dropdb does not work
---

To reset the Replit-managed development database, use `psql "$DATABASE_URL" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"`, then restart the backend workflow so it runs `migrate`, `taxonomy`, and `fixtures` on the empty schema.

**Why:** `dropdb`/`createdb` against the managed Postgres proxy (host `helium`) report success but leave the database contents untouched — the old `alembic_version` stamp and all tables survive. Observed Aug 2026 when a reset "succeeded" yet migration still failed on a stale revision reference. This also means the `dropdb`-based `reset_database` fallback in `scripts/replit-backend.sh` cannot recover on its own.

**How to apply:** any time a from-scratch database reset is needed (e.g. migration incompatibility, per project policy in replit.md), reset at the schema level, never at the database level. Verify with `SELECT count(*) FROM information_schema.tables WHERE table_schema='public'` returning 0 before rerunning the bootstrap.
