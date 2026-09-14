---
name: OpenAPI parameter description fallbacks
description: Explicit descriptions take precedence over centralized defaults
---

The control plane starts with FastAPI's generated OpenAPI schema. It fills missing parameter descriptions with `parameter.setdefault("description", _parameter_description(...))` in `control_plane/openapi.py`. Descriptions already supplied by a route or dependency are preserved.

The fallback uses parameter name, path, and location. A new endpoint without an explicit description can inherit text intended for another route with the same parameter name.

After adding parameters, inspect the exported spec. Supply an explicit description or refine the centralized fallback when needed, then regenerate the affected clients.
