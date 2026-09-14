---
name: Replit preview port routing
description: Checked-in preview mapping and historical Replit routing behavior
---

The checked-in `.replit` maps local port `20383` to external port `80`. `scripts/post-merge.sh` appends that mapping when no `[[ports]]` block exists. It does not repair an existing block with incorrect values.

In the earlier Replit environment, losing the mapping caused the preview to show backend API responses. Binding the backend to loopback and moving its port did not prevent this. If that symptom recurs, check the explicit mapping and the console's actual listening port first.

Port `20383` belongs to this Replit setup. Local Vite defaults to `5000` unless `PORT` overrides it. Do not impose the Replit preview port on other environments.

Earlier Replit workflow tooling could remove port mappings during restarts and required a dedicated tool for `.replit` edits. Those were environment-specific observations, not restrictions on editing the file in every checkout. Follow the tools and instructions available in the active environment.
