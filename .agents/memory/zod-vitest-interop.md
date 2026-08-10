---
name: zod named-export interop under vitest
description: Why `import { z } from 'zod'` breaks in console vitest runs and the safe import pattern.
---
Rule: in apps/console (and any package that also loads the generated api client), import zod as `import * as z from 'zod'`, never `import { z } from 'zod'`.

**Why:** When `@workspace/api-client-react` is in the module graph, vitest loads zod through a CJS interop path where the flattened exports (`object`, `string`, `ZodType`, ...) survive but the `z` named re-export is `undefined`. Tests then fail with `undefined is not an object (evaluating 'z.object')` while the app works fine under vite.

**How to apply:** Namespace imports (`import * as z` / `import type * as z`) work in both vite and vitest. If a suite fails with `z.object` undefined, check the import style first.
