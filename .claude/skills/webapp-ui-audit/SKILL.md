---
name: webapp-ui-audit
description: Clean-slate manual verification of apps/webapp against a running control plane. Use when a webapp change needs visual or behavioral proof, when asked to verify the console works, or after any change to auth, data fetching, or mutations. A passing build is not proof; this skill defines what is.
user-invocable: true
---

# Webapp UI Audit

Verify webapp behavior in a real browser against a real control plane. The repo rule for the gateway
is that proof is a real request against a running data plane; the webapp equivalent is observed
behavior in a running console, not a passing `bun run build`.

## Preflight, in order

Do not start scenarios until every step is confirmed. If one fails, stop and report which.

1. Control plane running on `127.0.0.1:8000` with a known admin token; start it from repo config if
   not running, and note whether the database already has data or is empty
2. Webapp dev server: kill any stale Vite process, then `cd apps/webapp && bun run dev`, confirm
   `http://localhost:5173` returns the console
3. Browser backend: Claude in Chrome tools. Open a fresh tab; never reuse a tab id from an earlier
   session
4. Clean slate: clear `localStorage` for `localhost:5173` so the token gate is exercised, not skipped

Seeding: scenarios need at least one org, provider, model, and key. Create them through the console
itself when the flow under test covers it, otherwise seed via the CLI or admin API and say which.

## Scenario set

Derive the feature-specific scenarios from the current diff: which pages, queries, or mutations
changed, and what user-visible behavior should differ. Then always run the base set:

1. Token gate: fresh load shows the gate; a wrong token produces a visible unauthorized error on
   data pages, not a blank screen; the correct token lands on Events
2. Every page in the sidebar renders one of data, empty state, or a readable error; never a spinner
   that outlives ten seconds and never an unstyled crash
3. One full mutation flow relevant to the diff, or key minting as the default: mint, see the
   show-once token banner, copy it, dismiss it, revoke the key, watch status flip without a manual
   reload
4. Polling: leave Events open, produce one usage event (real data plane request if the stack is up,
   otherwise note it was skipped), confirm the row appears within one polling interval
5. Reset token returns to the gate and no stale data flashes after re-auth

## Execution rules

- Judge readiness by what is on screen, never by waiting a fixed time
- Prefer stable targets (roles, visible labels) over brittle selectors
- Capture a screenshot at each scenario's success or failure point
- Never type a real admin token into logs or the report; refer to it by where it came from
- If the browser tooling fails twice in a row, stop and report rather than degrading the audit

## Pass/fail gates

Fail the audit if any of these occur:

- The token gate can be bypassed or a wrong token renders as anything but an auth error
- A page renders raw exception text, an empty white screen, or an infinite loader
- A mutation succeeds on the wire but the UI needs a manual reload to reflect it
- The Network panel shows request spam: the same endpoint fired more than once per polling interval,
  or catalog endpoints refetching without user action
- The show-once token is visible anywhere after dismissal

## Report

Return, concretely and metric-free of fluff:

1. Environment: control plane state (fresh or existing data), seeding performed
2. Scenarios run, each with pass or fail and one line of evidence
3. Screenshots captured, by path
4. Failures classified: product regression, environment problem, or audit-harness problem
5. Open risks and untested paths, called out rather than implied
