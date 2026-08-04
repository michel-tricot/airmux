---
name: webapp
description: Front door for apps/webapp React/TypeScript work. Use when changing anything under apps/webapp — components, pages, the API client, routing, or data fetching. Routes styling to webapp-styling, loading/effect patterns to react-patterns, cleanup passes to frontend-trim, and manual verification to webapp-ui-audit.
user-invocable: false
---

# Webapp Standards

The webapp is an admin console for the control plane, at `apps/webapp`. It is a pure client of the
control plane admin API. It never talks to the data plane and never grows its own persistence.
If a page needs data the API does not return, add the endpoint to the control plane, do not work around it.

## Stack

- Bun is the toolchain: `bun install`, `bun run dev`, `bun run build`. Never npm/npx/node
- Vite + React + TypeScript, Tailwind v4 via the `@tailwindcss/vite` plugin (no tailwind.config file)
- TanStack Query for all server state, react-router-dom for pages
- The Vite dev server proxies `/admin` to the control plane on `127.0.0.1:8000`; the browser never sees the control plane origin

## First move

Before editing, inspect nearby files and callsites. Reuse before creating:

- Shared primitives live in `src/ui.tsx`: `Page`, `Table`, `Td`, `Badge`, `Button`, `inputClass`, `QueryStatus`, `formatWhen`, `formatUsd`
- The typed API client lives in `src/api.ts`: one interface per resource matching the control plane response shape, one exported function per endpoint
- Pages live in `src/pages/`, one file per route, registered in both `NAV` and `Routes` in `App.tsx`

## Local contract

- Do not add a shared component, hook, or helper before the third real caller unless matching an existing local pattern
- Do not rewrite adjacent code for preference only: component style, naming, import shape, formatting
- All server data flows through TanStack Query. Query keys are the resource name (`['orgs']`, `['keys']`); mutations invalidate the list key they affect
- New endpoints get a typed function and interface in `src/api.ts`, never an inline `fetch`
- Auth is the bearer token from `getToken()`; the `api()` wrapper attaches it. Never store or log tokens elsewhere
- Render money with `formatUsd` and timestamps with `formatWhen`, do not roll new formatters per page
- Follow the repo style rules from CLAUDE.md: no comments unless asked, no emojis, no em dashes

## Route to other skills

- Tailwind classes, palette, shared primitives, extraction: `webapp-styling`
- Loading states, polling, effects, show-once data: `react-patterns`
- Simplification or cleanup pass over touched frontend files: `frontend-trim`
- Verifying changes against a running control plane: `webapp-ui-audit`

## Validation

- Every change: `cd apps/webapp && bun run build` (runs tsc then Vite, both must pass)
- Visual changes: run the dev server against a running control plane and look at the affected page; a passing build is not proof the UI works
