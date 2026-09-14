---
name: Replit development database reset
description: Existing helper behavior and the scope of a historical managed-Postgres workaround
---

`scripts/replit-backend.sh` currently handles a failed migration by dropping and recreating the `public` schema through `psql`, then rerunning migration and taxonomy import. It seeds fixtures when no users exist. The helper derives a libpq-compatible URL from the application URL before invoking `psql`.

This destroys the development schema and its data. The behavior belongs to that Replit development helper; it is not a general reset instruction for local, test, or production databases, and a migration failure alone does not establish that a reset is appropriate elsewhere.

The schema-level reset was introduced after `dropdb`/`createdb` appeared to succeed without removing data behind a particular Replit managed proxy in August 2026. Preserve that observation as historical context, not a claim about all managed Postgres services.

Repository tests use disposable Postgres databases and their own provisioning helpers. Keep their lifecycle separate from the Replit reset workflow.
