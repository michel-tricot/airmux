# Design records

The files in this directory capture the reasoning behind airmux's main architectural boundaries. They explain why a
design exists, which constraints it protects, and what consequences a change must preserve.

These are named, living design records rather than numbered chronological ADRs. Match that convention when updating the
architecture or adding a decision with no existing home.

## Records

| Record                                  | Focus                                                                                           |
| --------------------------------------- | ----------------------------------------------------------------------------------------------- |
| [Continuous integration](CI.md)         | Correctness, security, nightly, release, artifact, evidence, and merge-gate topology            |
| [Control-plane authority](AUTHORITY.md) | Principals, standing grants, credential ceilings, tenancy scopes, and delegated management keys |
| [Provider credentials](BYOK.md)         | Credential scopes, secret-store boundaries, selection rules, rotation, and failure behavior     |
| [Command line](CLI.md)                  | One public entry point, runtime packages, installation, and local configuration                |
| [Data plane](DATAPLANE.md)              | Canonical contracts, adapters, streaming, policy evaluation, metering, and the request path     |
| [Workspace policies](POLICIES.md)       | Rule composition, request matching, actions, fallback semantics, and extension boundaries       |

## Working with a design record

- Read the relevant record before changing the code it governs
- Update the record when shipped behavior changes its decision, constraints, or consequences
- Separate current behavior from explicitly labeled future work
- Record rejected alternatives when the reason would not be recoverable from code
- Link user-facing behavior to the corresponding page under `docs/`
- Preserve superseded reasoning when replacing a costly or security-sensitive decision

New records should describe the problem, decision, alternatives, consequences, and the tests or invariants that keep the
boundary intact. Avoid documenting obvious implementation details that are easier to verify in code.
