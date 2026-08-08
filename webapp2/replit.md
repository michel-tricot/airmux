# LLM Gateway Console

Admin console for an LLM gateway with the tenancy model: organizations → (members, management keys, workspaces); workspaces → (workspace members, inference keys); users are top-level and can belong to multiple orgs.

## Structure
- `lib/api-spec/openapi.yaml` — placeholder API contract (source of truth; codegen via orval into `lib/api-zod` and `lib/api-client-react`).
- `lib/db/src/schema/gateway.ts` — Drizzle schema (Postgres).
- `artifacts/api-server` — Express 5 stand-in backend implementing the contract with seed data.
- `artifacts/gateway-console` — React/Vite frontend ("Precision Control Room" design, Plus Jakarta Sans + Space Mono).

## Plan
The current backend is a placeholder. The user intends to later swap in their real LLM gateway backend by replacing the OpenAPI spec with their own and re-running codegen.

## User preferences
- User prefers Bun; this workspace runs Node/pnpm, so keep code Bun-compatible.
