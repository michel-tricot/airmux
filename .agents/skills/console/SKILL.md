---
name: console
description: Front door for apps/console React/TypeScript work. Use when changing anything under apps/console — pages, components, session and org scoping, or data fetching through the generated client. Routes styling to console-styling, loading/effect patterns to react-patterns, cleanup passes to frontend-trim, and manual verification to console-ui-audit.
user-invocable: false
---

# Console Standards

The console is the admin UI for the control plane, at `apps/console`. It is a pure client of the
control plane management API. It never talks to the data plane and never grows its own persistence.
If a page needs data the API does not return, add the endpoint to the control plane and regenerate
the client, do not work around it.

## Stack

- Bun is the toolchain, driven from the repo root: `bun install`, `bun run dev`, `bun run build`. Never npm/npx/node
- Vite + React + TypeScript, Tailwind v4 via the `@tailwindcss/vite` plugin (no tailwind.config file)
- TanStack Query for all server state, wouter for routing
- The Vite dev server proxies `/v1` to the control plane on `127.0.0.1:8000`, overridable with `CONTROL_PLANE_URL`.
  The API must answer on the console's own origin: the session cookie is same-site

## The generated client

`@workspace/api-client-react` is generated from `lib/api-spec/openapi.yaml` by orval. Never hand-write
a fetch or a resource interface.

- Hooks and query-key helpers come from the package: `useListOrgs`, `getListOrgsQueryKey`, `useCreateOrg`
- `customFetch` owns the wire: it strips the `{"data": ...}` envelope, attaches the CSRF header, raises `ApiError`
- A new endpoint means editing `lib/api-spec/openapi.yaml` and running `bun run codegen`, never a local shim
- Query keys are the request path, so they are shared across orgs. Anything org-scoped puts the org in the key too

## Auth and org scope

- Auth is the session cookie. There is no bearer token in the console and nothing auth-related in storage
- `src/lib/api.ts` sets `X-Requested-With` on every request once, at import. Do not set it per call
- Org-scoped calls under `/v1/org` pass `orgScope(orgId)` as the `request` option and carry the org in the query key
- `src/lib/session.tsx` owns the session: `useSession()` gives `user`, `orgId`, `setOrgId`, `logout`. Switching orgs
  drops every cached `/v1/org` query; logout clears the whole cache

## First move

Before editing, inspect nearby files and callsites. Reuse before creating:

- Shared primitives live in `src/components/ui/elements.tsx`: `Button`, `Input`, `Label`, `Badge`, `Card`, `Modal`, `Table`, `Tabs`
- The rest of `src/components/ui/` is the vendored shadcn set. Do not edit those files by hand; reach for one only when
  `elements.tsx` has no equivalent
- Formatters live in `src/lib/format.ts` (`formatDate`, `formatRelative`), class merging in `src/lib/utils.ts` (`cn`)
- Pages live in `src/pages/` (instance admin) and `src/pages/app/` (org member), registered in the matching
  `Switch` in `App.tsx`

## Local contract

- Two consoles share one app: instance-admin routes at the root behind `user.instance_admin`, org-member routes under `/app`.
  Put a page in the section whose permission it needs
- Do not add a shared component, hook, or helper before the third real caller unless matching an existing local pattern
- Do not rewrite adjacent code for preference only: component style, naming, import shape, formatting
- All server data flows through the generated hooks. Mutations invalidate the list key they affect via its `get*QueryKey` helper
- Render timestamps with `formatDate` or `formatRelative`, do not roll new formatters per page
- Follow the repo style rules from CLAUDE.md: no comments unless asked, no emojis, no em dashes

## Route to other skills

- Tailwind classes, theme tokens, shared primitives, extraction: `console-styling`
- Loading states, polling, effects, show-once data: `react-patterns`
- Simplification or cleanup pass over touched frontend files: `frontend-trim`
- Verifying changes against a running control plane: `console-ui-audit`

## Validation

- Every change: `bun run typecheck` from the repo root, and `bun run build` when the change touches the build
- Visual changes: run the dev server against a running control plane and look at the affected page; a passing build is not proof the UI works
