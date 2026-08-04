# M4 finding: did the eight-method adapter interface survive a native adapter?

The spec (§4.2, §5-M4) predicted the OpenAI-first interface would be wrong in three
ways a native adapter exposes, and pre-corrected for them: framing owned by the
adapter, adapter-shaped `StreamState`, and `finalize()` valid mid-stream. The
instruction was to write down whatever still had to change.

## The interface did not change

The eight abstract methods, their signatures, and `RawEvent`/`StreamState`/`Ctx`
were untouched. `AnthropicAdapter` is a peer of `OpenAICompatibleAdapter` with no
edits to `base.py`, `app.py`, or the transport. The three pre-corrections all paid
off exactly as intended:

- **Framing belongs to the adapter.** OpenAI `frame()` reads `data:` lines and a
  `[DONE]` sentinel. Anthropic `frame()` reads `event: <name>` + `data:` pairs and
  carries the event name across a read boundary in `pending_event`. The transport
  parses neither. `RawEvent.name` — flagged as unused during the M2 cleanup — is
  what the Anthropic framer populates; keeping it was correct.

- **`StreamState` is adapter-shaped.** `AnthropicStreamState` accumulates content
  *blocks by index* (`dict[int, _Block]`), tracks `pending_event`, and splits usage
  across `message_start` (input) and `message_delta` (output). None of that fits the
  OpenAI state, and it did not have to.

- **`finalize()` valid at any prefix** held with no special-casing. The
  finalize-at-every-prefix conformance test passes for Anthropic's multi-event,
  named-SSE stream the same way it does for OpenAI's.

## What this cost, and the one thing worth noting

The genuinely shared thing is the *canonical output shape*, not the interface.
`content_blocks()` (reasoning, text, tool calls) now has one definition both
adapters call, and finish reasons normalize to one vocabulary
(`end_turn`->`stop`, `tool_use`->`tool_calls`, ...). That extraction was the whole
delta — the interface generalized, the canonical shape needed a single owner.

The one honest asymmetry: the two providers disagree on where a tool call's name
lives in the stream. OpenAI streams `id`+`name` in the first tool-call delta;
Anthropic streams them in `content_block_start` and only the JSON arguments in the
deltas. Both converge to identical canonical content because `finalize()`
reassembles from accumulated state rather than trusting any single event — which is
the point of the invariant. If a third adapter (Bedrock, Gemini) streamed the name
*last*, the interface would still hold; only that adapter's state machine changes.

## Verdict

The interface was real. The M2-era prediction that framing, state ownership, and
partial finalize are the three things a native adapter breaks was correct, and
pre-correcting them meant M4 added a file and touched nothing else — the structural
goal of §4.2 ("adding an adapter means adding one module"). The conformance suite is
now parametrized over both adapters (§6.5): 6 shared invariants x 2 adapters x 3
modalities, no per-adapter suites.
