---
name: frontend-trim
description: Behavior-preserving simplification of frontend React/TypeScript code already in your diff. Use when removing useMemo/useCallback, collapsing conditional spreads, passing optional fields as undefined, deleting unused-looking props, or reconstructing objects — and for any cleanup or simplify pass over touched webapp files. Encodes which frontend redundancies are load-bearing so a trim does not silently change behavior.
user-invocable: true
---

# Frontend Trim Pass

A trim must be behavior-preserving. The trap in frontend code is that apparent redundancy is often
load-bearing: the presence of an object key, the referential identity of a value, a spread-forwarded
prop, or a type's shape each carries behavior a naive cleanup destroys. For each trim, confirm the
condition that makes it safe; otherwise leave the code alone. A trim you cannot prove safe is a bug.

Scope: touched files only. Do not open files just to clean them, and do not turn a reviewable diff
into an unreviewable cleanup PR.

## Presence semantics

`{ key: undefined }`, `{ ...(cond && { key }) }`, and omitting the key are three different payloads
even when they render identically. Before collapsing them, check how the value is consumed:

- Request bodies: a present key can mean "set this field", an absent one "leave it unchanged".
  `JSON.stringify` drops `undefined`, which may be exactly the behavior the spread was protecting
- Query strings: the `api.ts` helpers build URLs by hand; an empty param and an absent param can hit
  different control plane filters (`org_id=` vs no filter)
- Empty array vs absent: `allowed_models: []` and omitting the field are different requests

Pass an optional field as `undefined` only when the consumer provably strips nullish values.

## Referential identity

`useMemo`/`useCallback` do two jobs: skip recomputation, and give a value stable identity. The second
is invisible until removal makes something downstream re-run every render. A memo is load-bearing
whenever anything reads its result by reference: an effect or memo dependency array, a `React.memo`
child's props, a context provider `value`, a comparator. Trace consumers before removing. If the
value is used only inline in the same render and is cheap, the hook is noise; drop it.

## Prop forwarding

An unreferenced prop next to a `{...rest}` spread cuts both ways:

- Forwarded: a prop not destructured flows through the spread to a child or DOM node; deleting it
  from the type silently breaks the forward
- Deliberately stripped: a prop destructured and never used may exist precisely to keep it out of
  `rest` so it does not leak onto a DOM element; removing the destructure leaks it

Confirm which case you are in before touching either.

## Type shape

- Prefer handing a callback the original object over reconstructing a field subset like
  `{ id: item.id }`; reconstruction silently narrows the shape, and the day the callback needs
  another field it gets `undefined` with no error. Reconstruct only when narrowing is the intent
- The interfaces in `src/api.ts` mirror control plane response shapes. Do not trim fields from them
  because no component reads them yet; the interface documents the wire contract

## Defaults: confirm whose default it is

A value is redundant only when it equals the default its direct consumer applies, and that is not
always the library's default. `main.tsx` sets `retry: 1` and `refetchOnWindowFocus: false` app-wide,
so a per-query `retry: 1` is redundant, but a per-query `retry: 3` or `refetchOnWindowFocus: true`
is an override and load-bearing. Anything computed is always load-bearing: `enabled: foo ?? true`
is a guard, not a restatement, because `foo === false` disables the query. Do not add restatements
of effective defaults either.
