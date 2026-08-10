---
name: Replit workflow host binding
description: When a workflow-monitored service needs 0.0.0.0 vs deliberate loopback-only binding.
---

Bind `0.0.0.0` ONLY when a workflow uses `waitForPort` on that port — the port monitor can't see loopback, so the workflow times out even though the server started. Conversely, if a service must stay invisible to Replit's port detector (so it can never steal the preview), bind `127.0.0.1` AND remove `waitForPort` from its workflow.

**Why:** the control-plane backend originally bound 0.0.0.0 for `waitForPort`, which let the preview router pick it up and serve API JSON instead of the console whenever port pinning was lost. Now it binds loopback with no `waitForPort` (see preview-port-routing.md).

**How to apply:** the two settings must move together: `waitForPort` ⇔ `0.0.0.0`; no `waitForPort` ⇔ loopback-only for internal services.
