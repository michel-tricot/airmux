---
name: react-patterns
description: React data and lifecycle patterns for apps/webapp — query conventions, polling cadence, loading and empty states, show-once data, and effect cleanup. Use when writing or modifying components or hooks that fetch, poll, mutate, or manage loading states.
user-invocable: false
---

# React Patterns

## Query conventions

- One query key per resource, named after it: `['orgs']`, `['keys']`, `['events']`. A filtered query
  appends its params: `['events', { orgId }]`
- Mutations invalidate the list key they change, nothing broader. Minting a key invalidates `['keys']`,
  not the whole cache
- Cross-resource reads (an org dropdown on the Keys page) reuse the owning resource's query, they do
  not refetch under a new key
- `QueryClient` defaults live in `main.tsx`. Change behavior for one query on that query, change
  behavior for the app in `main.tsx`, never both

## Polling

Polling is a per-page decision based on how fast the data actually changes:

- Live operational data (events): `refetchInterval: 3000`
- Slowly changing operational data (instance heartbeats): `refetchInterval: 10000`
- Catalog data (orgs, keys, providers, models, bundles): no polling; it changes when the user acts,
  and the mutation invalidation covers that

Do not add polling to a page as a substitute for invalidating after a mutation. When real push is
needed, the upgrade path is SSE from the control plane, not tighter polling.

## Loading, error, empty

Every query-backed page renders all three states through `QueryStatus` before rendering data. The
error branch must stay useful when the control plane is down or the token is wrong; `ApiError`
carries the status and a 401 should read as a token problem, not a generic failure.

Avoid loading flashes: content that usually arrives fast should not blink a spinner for one frame.
Prefer rendering nothing over a sub-100ms spinner. If a flash shows up in practice, gate the loader
on a minimum elapsed time in a small shared hook rather than sprinkling timeouts per page.

## Show-once data

Some API responses appear exactly once and can never be refetched, like the token returned when a
key is minted. Rules:

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

If the console grows modals, slideouts, or other animated containers: do not suspend inside them.
A Suspense boundary that blocks inside an animating panel prevents the panel from rendering until
data lands, killing the animation. Fetch with a plain `useQuery`, open the container immediately,
and render the loading state as its children.
