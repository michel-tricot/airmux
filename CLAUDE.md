# airllm gateway prototype

## Boundary rules, non-negotiable
- data_plane may never import sqlalchemy, sqlmodel, asyncpg, alembic, fastapi, or control_plane.
- The only shared import between planes is contract.
- If a feature seems to need a DB read on the request path, add a field to the bundle instead. Say so before doing it.
- evaluate() must stay pure: no async, no network, no I/O, no datetime.now(). Under 100 lines.

## Adding an adapter
One new module under apps/data-plane/src/data_plane/adapters/. Subclass ProviderAdapter, set `kind`,
implement the eight methods. Touch no other file. If you think you need to edit a registry, the registry
is wrong; fix the registry.

- The transport never parses SSE. frame() owns wire framing and the partial-line buffer.
- StreamState is adapter-shaped. Construct it in new_stream_state(), never in the transport.
- finalize(state) must return a valid CanonicalResponse at ANY point in the stream, including
  after a client disconnect. Cancellation accounting depends on this.
- frame() and transform_stream_event() stay synchronous so the streaming path is testable as a
  pure fold over a recorded byte log.

## Typing and lint
ty must pass clean. Do not widen to Any to silence an error, and do not add `# ty: ignore` or a blanket
`# noqa`. Fix the type or ask. Every suppression that does survive must name the exact rule and carry a
reason on the same line.
Prefer immutable construction: build with comprehensions and freeze, rather than seeding an empty
dict or list and mutating it.
Line length is 150. Do not reformat unrelated lines to fit; run `ruff format` and leave it alone.

## Testing
- Write the failing test first, in the same commit.
- No test that asserts a function was called. Assert behaviour or observable output.
- Adapter tests are parameterized over all registered adapters. Do not write per-adapter suites.
- Proof of fix is a real request against a running data plane, not pytest output.

## Style
No comments unless asked. No emojis. No em dashes. No trailing periods in bullets.
Do not add Claude attribution to commits or PRs.
