---
name: Preview port routing pinning
description: Why .replit has explicit [[ports]] entries pinning the console to external port 80
---

The console (vite, PORT 20383) and the Python control plane (uvicorn, 0.0.0.0:8000) both open ports. Without explicit `[[ports]]` mappings, the platform guessed which port owns the public preview route; when both workflows restarted simultaneously, the backend's 8000 sometimes won and the preview served the API's `{"detail":"Not Found"}`.

**Why:** happened in practice after restarting both workflows in one batch (Aug 2026).

**How to apply:** keep the `[[ports]]` block in `.replit` — console 20383 → externalPort 80, backend 8000 with `exposeLocalhost = true` (local-only). If any artifact port changes, update the mapping: once any `[[ports]]` entries exist, every artifact port must be represented. `.replit` can only be edited via `verifyAndReplaceDotReplit` with a temp file.
