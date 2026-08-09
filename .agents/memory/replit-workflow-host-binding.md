---
name: Replit workflow host binding
description: Long-running support services monitored by Replit must bind their listen host to the workspace network.
---

Replit workflow port detection requires backend servers to listen on `0.0.0.0`, not only `127.0.0.1`.

**Why:** A control-plane process can report that Uvicorn started successfully while Replit still marks the workflow failed if the monitored port is loopback-only.

**How to apply:** When a non-artifact backend is exposed through a Replit workflow with `waitForPort`, pass the service's host/network binding explicitly.