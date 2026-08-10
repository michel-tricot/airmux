---
name: Append-only schema compatibility
description: Handling schema fields added to an already-stamped Alembic revision in this control-plane project
---

When a schema revision has already been applied to a development database, never rely on editing that revision to add a field. Add a forward compatibility migration that conditionally creates and backfills the field, then adds its constraints.

**Why:** The workspace slug change had been consolidated into the initial revision, but the running database was already stamped at that revision without the column. The ORM then failed at runtime even though the source migration looked correct.

**How to apply:** For audited tables, set the transaction-local audit actor to `root` before migration backfills. Use the project’s normal `airllmcp migrate` startup path and verify both the new Alembic head and the affected endpoint after restarting the backend.