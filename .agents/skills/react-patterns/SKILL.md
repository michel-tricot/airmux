---
name: react-patterns
description: React data and lifecycle patterns for apps/console — query conventions, polling cadence, loading and empty states, show-once data, and effect cleanup. Use when writing or modifying components or hooks that fetch, poll, mutate, or manage loading states.
user-invocable: false
---

# React Patterns

## Query conventions

- Management queries and mutations use generated `@workspace/api-client-react` hooks, preferably through
  existing `src/features/*/hooks.ts` wrappers that own permissions-aware enabling and invalidation.
  Never hand-write a management `useQuery` over a raw fetch; the separate playground inference boundary
  lives in [console](../console/SKILL.md#playground-inference)
- Let generated hooks build their keys. When a key is needed explicitly, use the matching generated
  `get*QueryKey` helper with the same scope and filter arguments; never spell it out or append scope manually
- Generated keys contain the request path with scope arguments substituted and query params where present, so
  `getListWorkspacesQueryKey(orgId)` and `getGetWorkspaceQueryKey(orgId, workspaceRef)` already isolate scope.
  Permission queries use `getMyPermissionsQueryKey(params)`, including org and workspace filters in the key
- Infinite queries use distinct `get*InfiniteQueryKey` helpers, such as `getListOrgsInfiniteQueryKey()`.
  Reuse `paginatedQueryOptions` and `flattenPages` from `src/features/pagination.ts` for cursor-backed lists
- Mutations invalidate the affected list, detail, and dependent queries through their generated helpers.
  Follow the owning feature hook: renaming an org refreshes its list, detail, and enrollment data.
  Avoid clearing the whole cache for an ordinary resource mutation
- Cross-resource reads (an org dropdown on a workspace page) reuse the owning resource's query, they do
  not refetch under a new key
- `QueryClient` defaults live in `App.tsx`. Change behavior for one query on that query, change
  behavior for the app in `App.tsx`, never both

## Polling

`src/features/telemetry/hooks.ts` centralizes the existing polling cadence:

- Live operational data (usage events): `refetchInterval: 3000`
- Slowly changing operational data (data plane heartbeats): `refetchInterval: 10000`
- Catalog data (orgs, users, workspaces, keys, providers, models, bundles): no polling; it changes when
  the user acts, and the mutation invalidation covers that

Choose any additional polling based on how fast the data changes. Do not add it to a page as a substitute
for invalidating after a mutation. When real push is needed, the upgrade path is SSE from the control plane,
not tighter polling.

## Loading, error, empty

Every query-backed page renders all three states before rendering data, in that order: `isLoading` first,
then a readable error, then the empty state when the list comes back empty. A page that only branches on
`isLoading` and then indexes the data is a blank screen waiting to happen. The error branch must stay
useful when the control plane is down or the session has expired; `ApiError` carries the status, and a
401 should read as a session problem, not a generic failure.

Avoid loading flashes: content that usually arrives fast should not blink a spinner for one frame.
Prefer rendering nothing over a sub-100ms spinner. If a flash shows up in practice, gate the loader
on a minimum elapsed time in a small shared hook rather than sprinkling timeouts per page.

## Show-once data

Some API responses appear exactly once and can never be refetched, like the token returned when a
key is minted. `KeyRevealDialog` is the pattern; follow it. Rules:

- Hold it in component state from the mutation result, never in the query cache
- Keep it visible until the user explicitly dismisses it, with a copy action
- Say in the UI that it will not be shown again
- Never log it or write it to storage

## Effects and cleanup

Most data flow belongs in TanStack Query, so a `useEffect` is rare and deserves suspicion. When one
is genuinely needed:

- Every subscription-like effect returns a cleanup: `removeEventListener`, `clearInterval`,
  `AbortController.abort`, socket close
- Timers for UI polish (copied feedback, delayed loaders) are cleared on unmount
- An effect that only derives state from props or query data should not exist; compute during render

## Animated containers

`Modal` and the other Radix containers animate on open, so do not suspend inside them. A Suspense
boundary that blocks inside an animating panel prevents the panel from rendering until data lands,
killing the animation. Fetch with the generated hook, open the container immediately, and render the
loading state as its children.
