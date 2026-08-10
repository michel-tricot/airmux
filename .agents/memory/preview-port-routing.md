---
name: Preview port routing pinning
description: Why the backend must stay loopback-only so the console keeps the dev preview
---

The dev preview must always route to the console (Vite), never the FastAPI backend. The one durable mechanism: the backend serves loopback-only (`--host 127.0.0.1` in `scripts/replit-backend.sh`) with NO `waitForPort` in its workflow. That keeps the backend invisible to Replit's port detector, so the console's port is the only preview candidate. The console's Vite proxy reaches the backend over loopback, so nothing else is needed.

**Why:** a `[[ports]]` pin in `.replit` was tried repeatedly, but task merges and workflow-manager rewrites keep stripping it — every time it vanished while the backend bound 0.0.0.0, the preview showed the API's `{"detail":"Not Found"}`. Do not rely on `[[ports]]` surviving; do not re-add `waitForPort` to the backend workflow (a loopback port would make it time out); do not switch the backend back to 0.0.0.0.

**How to apply:** if the preview ever shows backend JSON again, check the backend host binding first, then restart `apps/console: web` so its port re-registers (stale routing can persist until it re-announces). `.replit` may only be edited via `verifyAndReplaceDotReplit` with `tempFilePath` set to an ABSOLUTE path INSIDE the workspace.
