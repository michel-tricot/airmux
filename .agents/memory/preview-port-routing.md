---
name: Preview port routing pinning
description: What actually keeps the dev preview on the console instead of the FastAPI backend
---

The dev preview routes to the FastAPI backend instead of the console whenever `.replit` loses its `[[ports]]` block (`localPort = 20383`, `externalPort = 80`). Loopback-only backend binding does NOT prevent this: Replit's port detector sees loopback listeners too and follows the backend across port changes (verified — moving the backend 8001→8101 changed nothing while the block was missing). The `[[ports]]` pin is the mechanism that works; the backend also binds `127.0.0.1` with no `waitForPort`, which is still correct but is defense-in-depth only.

**Why:** task merges and workflow restarts repeatedly stripped the block; each time, the domain served `{"detail":"Not Found"}` from the API. Re-adding the block immediately restored the console — no restarts needed. `scripts/post-merge.sh` now re-appends the block after merges if missing.

**How to apply:** apply the `[[ports]]` block AFTER any workflow restarts (restarts can strip it; re-adding it takes effect without restarting anything). `.replit` may only be edited via `verifyAndReplaceDotReplit` with `tempFilePath` an ABSOLUTE path INSIDE the workspace. If the preview shows backend JSON, check `tail .replit` for the block first — that has always been the cause.
