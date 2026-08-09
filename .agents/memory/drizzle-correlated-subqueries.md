---
name: Drizzle correlated subqueries
description: Column interpolation inside sql`` scalar subqueries breaks correlation
---
Interpolating a Drizzle column (e.g. `${organizationsTable.id}`) inside a sql`` scalar subquery renders it as an unqualified `"id"`, which resolves to the *subquery's* table — the correlation silently returns wrong counts, no error.
**Why:** drizzle doesn't table-qualify columns in raw sql fragments.
**How to apply:** write correlated count subqueries as fully qualified raw SQL text, e.g. `sql<number>`(select count(*)::int from org_members where org_members.org_id = organizations.id)``. Verify counts with a direct SQL query when in doubt.
