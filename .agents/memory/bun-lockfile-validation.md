---
name: Bun lockfile validation
description: Portable lockfile cleanup and validation conventions for this Bun workspace.
---

Bun lockfiles are JSON-like rather than strict JSON, so a standard JSON parser can reject a valid lockfile because of trailing commas.

**Why:** The repository's lockfile uses Bun's native format, and the reliable portability check is whether Bun can consume it with the intended public registry and frozen-lockfile mode.

**How to apply:** For lockfile-only portability changes, preserve package versions, dependency metadata, and integrity hashes, then run `bun install --frozen-lockfile --registry=https://registry.npmjs.org` and compare the diff to confirm only the intended resolved URL fields changed.