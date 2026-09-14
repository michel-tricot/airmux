---
name: Zod namespace imports in console code
description: Current import convention and an unverified historical Vitest interop workaround
---

Console code uses namespace imports such as `import * as z from 'zod'` and `import type * as z from 'zod'`. Preserve that convention when touching existing code.

An earlier Vitest environment reportedly exposed `z` as undefined for `import { z } from 'zod'` when the generated API client was loaded, while namespace exports remained available. That failure has not been reproduced against the current dependency versions, so it should not be stated as a universal limitation of named imports.

Before removing the workaround, reproduce the relevant import order under the current console Vitest configuration and verify both tests and the Vite build. This is separate from the generated API validators' required `zod/v4` import rewrite.
