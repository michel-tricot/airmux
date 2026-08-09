---
name: Orval zod v4 import
description: Why the api-spec codegen script rewrites the generated zod import
---
Orval emits `zod.int()` which doesn't exist on zod 3.25.x's default (v3) entry.
**Why:** the workspace pins zod 3.25.x where v4 API lives under `zod/v4`.
**How to apply:** the `lib/api-spec` codegen script includes a post-orval `node -e` step rewriting the generated file's import from `'zod'` to `'zod/v4'`. Keep it when changing codegen; it must run before typecheck.
