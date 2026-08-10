---
name: Preview port routing pinning
description: Why the console owns the external preview port and the backend stays on a separate local port
---

The console (Vite, PORT 20383) and the Python control plane (Uvicorn, 0.0.0.0:8001) both open ports. Without explicit `[[ports]]` mappings, the platform guessed which port owns the public preview route; when both workflows restarted, the backend sometimes won and the preview served the API's `{"detail":"Not Found"}`.

**Why:** happened in practice after restarting both workflows in one batch (Aug 2026).

**How to apply:** keep the `[[ports]]` block in `.replit` — console 20383 → externalPort 80, backend 8001 with `exposeLocalhost = true` (local-only). The Vite proxy must target 8001, and the backend workflow must wait for 8001. If any artifact port changes, update the mapping: once any `[[ports]]` entries exist, every artifact port must be represented. `.replit` can only be edited via `verifyAndReplaceDotReplit` with a temp file.
