---
name: console-ui-audit
description: Clean-slate manual verification of apps/console against a running control plane. Use when a console change needs visual or behavioral proof, when asked to verify the console works, or after any change to auth, org scoping, data fetching, or mutations. A passing build is not proof; this skill defines what is.
user-invocable: true
---

# Console UI Audit

Verify console behavior in a real browser against a real control plane. The repo rule for the gateway
is that proof is a real request against a running data plane; the console equivalent is observed
behavior in a running browser, not a passing `bun run build`.

## Preflight, in order

Do not start scenarios until every step is confirmed. If one fails, stop and report which.

1. Control plane running on `127.0.0.1:8000`; start it from repo config if not running, and note
   whether the database already has data or is empty
2. Console dev server: kill any stale Vite process, then `bun run dev` from the repo root, confirm
   `http://localhost:5000` returns the console
3. Browser backend: Claude in Chrome tools. Open a fresh tab; never reuse a tab id from an earlier
   session
4. Clean slate: clear cookies and `localStorage` for `localhost:5000` so the login gate and the org
   picker are exercised, not skipped

Accounts: the base set needs one instance admin and one plain member in at least two orgs, so the
admin section, the `/app` section, and the org switch are all reachable. Sign up through the console
when the flow under test covers it, otherwise seed via the CLI or management API and say which.

## Scenario set

Derive the feature-specific scenarios from the current diff: which pages, queries, or mutations
changed, and what user-visible behavior should differ. Then always run the base set:

1. Login gate: fresh load shows the login page; wrong credentials produce a visible sign-in error, not
   a blank screen; correct credentials land on the section the account's role allows
2. Role routing: an instance admin gets the admin section at `/`; a plain member hitting `/` is
   redirected to `/app`, and their org selection sticks across a reload
3. Every page in the sidebar renders one of data, empty state, or a readable error; never a spinner
   that outlives ten seconds and never an unstyled crash
4. Org switch: change orgs from the picker and confirm the page repopulates with the new org's data
   with no row from the previous org left on screen
5. One full mutation flow relevant to the diff, or org creation as the default: create, watch the list
   update without a manual reload
6. Show-once secret: mint a key, see the reveal dialog, copy it, dismiss it, confirm it is gone from
   the UI and never refetched
7. Logout returns to the login page, and signing back in shows no stale data from the previous session

## Execution rules

- Judge readiness by what is on screen, never by waiting a fixed time
- Prefer stable targets (roles, visible labels) over brittle selectors
- Capture a screenshot at each scenario's success or failure point
- Never type a real password or minted secret into logs or the report; refer to it by where it came from
- If the browser tooling fails twice in a row, stop and report rather than degrading the audit

## Pass/fail gates

Fail the audit if any of these occur:

- The login gate can be bypassed, or a signed-out load renders anything but the login page
- A plain member reaches the instance admin section, or a stale stored org survives losing membership
- A page renders raw exception text, an empty white screen, or an infinite loader
- A mutation succeeds on the wire but the UI needs a manual reload to reflect it
- The Network panel shows request spam: the same endpoint firing repeatedly without user action
- An org switch leaves the previous org's data on screen, or the cache serves one org's rows under another
- The show-once secret is visible anywhere after dismissal

## Report

Return, concretely and free of fluff:

1. Environment: control plane state (fresh or existing data), accounts and orgs seeded
2. Scenarios run, each with pass or fail and one line of evidence
3. Screenshots captured, by path
4. Failures classified: product regression, environment problem, or audit-harness problem
5. Open risks and untested paths, called out rather than implied
