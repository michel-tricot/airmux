---
name: OpenAPI query param descriptions are centralized
description: Where query parameter descriptions come from when adding control-plane endpoints
---

Query parameter descriptions in the exported OpenAPI spec come from `_parameter_description` in the control plane's openapi module, keyed by parameter name (and sometimes path), not from the route signature.

**Why:** a new endpoint reusing a common param name (e.g. `org_id`) silently inherits another route's description, which then flows into the generated clients.

**How to apply:** after adding a control-plane endpoint with query params, check the exported spec's description text and add a path-specific branch when the shared description is wrong.
