---
name: console
description: Front door for apps/console React/TypeScript work, including routing, session and organization scope, management data, and playground inference. Routes styling to console-styling, query and lifecycle patterns to react-patterns, cleanup to frontend-trim, and manual verification to console-ui-audit.
user-invocable: false
---

# Console Standards

The console at `apps/console` manages resources through the control plane and sends playground
inference to the data plane. Resource state belongs to the management API. If a page needs resource
data the API does not return, add the endpoint to the control plane and regenerate the client.
Console-local paths below are relative to `apps/console`.

## Stack

- Bun is the toolchain, driven from the repo root: `bun install`, `bun run dev`, `bun run build`. Never npm/npx/node
- Vite + React + TypeScript, Tailwind v4 via the `@tailwindcss/vite` plugin (no tailwind.config file)
- TanStack Query for management server state, wouter for routing
- `vite.config.ts` proxies `/api` to `http://127.0.0.1:8000` (`CONTROL_PLANE_URL`) and `/inf` to
  `http://127.0.0.1:8080` (`DATA_PLANE_URL`), preserving both prefixes
- Browser calls use the console's own origin so management and playground cookies reach their APIs

## Management API

`@workspace/api-client-react` is generated from the repo's `lib/api-spec/openapi.yaml` by orval.
Management calls use its hooks and types, usually through the existing `src/features/*/hooks.ts`
wrappers. Never hand-write a management fetch, duplicate a resource interface, or edit generated files.

- The repo's `lib/api-client-react/src/custom-fetch.ts` unwraps `{"data": ...}`, converts paginated
  envelopes to `{ items, page }`, applies configured headers, and raises `ApiError`; callsites never unwrap envelopes
- `src/lib/api.ts` configures `X-Requested-With` once via `setDefaultHeaders`; do not repeat it per management call
- After changing an endpoint, run `./scripts/export-openapi.sh` and `bun run codegen` from the repo root
- [react-patterns](../react-patterns/SKILL.md#query-conventions) owns query keys, pagination, and invalidation

## Playground inference

- `src/pages/app/workspace/Playground.tsx` uses the generated management mutations wrapped in
  `src/features/playground/hooks.ts` to ensure or end a workspace's playground session
- Before each completion, `useEnsurePlaygroundSessionMutation` sends `PUT` to
  `/api/v1/organizations/{orgId}/workspaces/{workspaceRef}/playground-session`; the control plane sets or
  reuses an HttpOnly playground cookie and returns session metadata
- `src/lib/inference.ts` owns `prepareInferenceRequest` and `inferenceCompletion`, posting to
  `/inf/v1/chat/completions` with the playground cookie and its own `X-Requested-With` header
- Keep inference's direct fetch, response validation, streaming, cancellation, and bounded session-propagation
  retries in that module; inference responses do not use management envelopes or `customFetch`
- Catalog reads and playground-session mutations still use the generated management client

## Auth and org scope

- `src/lib/session.tsx` owns the cookie-authenticated session through generated `useMe` and `useLogout`
  calls to `/api/v1/auth/me` and `/api/v1/auth/logout`; keep credentials out of browser storage
- `useSession()` exposes `user`, `isLoading`, `error`, `retry`, `isRetrying`, `orgId`, `setOrgId`, and `logout`
- `orgId` is a selection preference stored as `airmux_org_id` in localStorage.
  `AppSection` in `src/App.tsx` validates it against `useEnrollment()` data from `/api/v1/enroll`, clears a
  stale selection, and redirects to `/orgs` when selection is needed
- Org pages use `useRequiredOrgId()`; route parameters use `useRequiredParam()` from `src/lib/route.ts`.
  Instance detail pages take their org from the route
- Pass `orgId` and `workspaceRef` to the generated hooks or their feature wrappers; scoped resource paths
  are `/api/v1/organizations/{orgId}/...` and `/api/v1/organizations/{orgId}/workspaces/{workspaceRef}/...`
- Switching orgs updates the selection without clearing the query cache; generated keys isolate scoped data.
  Logout clears the selection and the whole query cache when its mutation settles
- `src/features/permissions/hooks.ts` owns `AuthorizationProvider`, `useAuthorization`, and
  `useScopedAuthorization`; use the scope's permissions and feature policies to gate pages, controls, and queries

## Routes

`src/App.tsx` mounts route definitions with their access policies. Register pages in the matching definition:

| Section | Browser path | Definition |
|---------|--------------|------------|
| Instance | `/instance/...` | `src/pages/instance-routes.tsx` |
| Organization | `/org/...` | `src/pages/app/routes.tsx` |
| Workspace | `/org/workspaces/:workspaceRef/...` | `src/pages/app/workspace/routes.tsx` |

`/` redirects to `/org` when an org is selected, otherwise `/orgs`; `src/components/layout/AppLayout.tsx`
can then select the last or first workspace. Instance routes require `user.instance_role` plus the
route's permission policy. `/orgs` is the enrollment picker, `/cli` handles CLI approval, and `/invite`
handles invitations, including signed-out access.

## First move

Before editing, inspect nearby files and callsites. Reuse before creating:

- Inspect `src/components/ui/elements.tsx` for themed primitives, `src/components/shared/` for product
  compositions, and the vendored `src/components/ui/` foundation before writing styled markup
- Pages compose these components; follow [console-styling](../console-styling/SKILL.md) for reuse,
  extension, extraction, and accessible behavior instead of rebuilding existing interactions
- Use `formatDate` from `src/lib/format.ts` for timestamps and `cn` from `src/lib/utils.ts` for class merging
- Do not rewrite adjacent code for preference only: component style, naming, import shape, formatting

## Route to other skills

- Tailwind classes, theme tokens, shared primitives, extraction: [console-styling](../console-styling/SKILL.md)
- Query conventions, loading states, polling, effects, show-once data: [react-patterns](../react-patterns/SKILL.md)
- Simplification or cleanup pass over touched frontend files: [frontend-trim](../frontend-trim/SKILL.md)
- Verifying running console behavior: [console-ui-audit](../console-ui-audit/SKILL.md)

## Validation

- Console code changes: `bun run typecheck` from the repo root, and `bun run build` when the change touches the build
- Visual or behavioral changes: follow the linked audit skill against running services, including the data plane for playground inference
