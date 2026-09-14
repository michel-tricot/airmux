---
name: Replit workflow host binding
description: Current backend binding and the limits of historical workflow-monitor advice
---

The checked-in backend workflow runs `scripts/replit-backend.sh` without `waitForPort`. The helper binds the control plane to `127.0.0.1:8101`, and the console proxy uses that address through the shared `CONTROL_PLANE_URL` setting.

An earlier Replit environment required `0.0.0.0` for a workflow's `waitForPort` monitor to report readiness. Treat that as an environment-specific observation to recheck when changing workflows, not a universal rule for service binding.

Loopback binding does not make the backend invisible to the preview router. The later routing investigation found that explicit port mapping was necessary; see [preview port routing](preview-port-routing.md). Keep network exposure, workflow readiness, and preview routing as separate configuration concerns.
