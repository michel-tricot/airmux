# Command line

TokKeeper has one public executable, `tokkeeper`. It manages remote installations and starts local runtimes through
`gateway` and `control-plane` command groups. The CLI owns Typer, help, output, and actionable command errors. Each runtime
owns typed operations and its application factory. Neither runtime imports the CLI, and the planes still share only `contract`.

Shared taxonomy definitions live in `contract` as `ProviderSpec`, `ModelSpec`, and `TaxonomySpec`, so standalone file loading
has no control-plane dependency. Control-plane `ProviderIn`, `ModelIn`, and `TaxonomySpec` retain `RequestModel` inheritance
and reuse those definitions. API responses retain their `RecordOut` models. Sharing file validation does not remove the
request and response boundaries.

## Installation boundary

The `tokkeeper` distribution provides remote management without installing either server. The `gateway` and `control-plane`
extras add the corresponding runtime. Workspace distributions use the `tokkeeper-` prefix and exact matching versions;
Python import names remain `cli`, `contract`, `control_plane`, and `data_plane`. The workspace root is not the CLI distribution.

Runtime imports happen only when their commands execute. Help and command inventory are available in every installation.
Missing extras produce a direct installation instruction. Separate server executables and subprocess forwarding would
create multiple public interfaces and inconsistent errors, so neither is retained. Control-plane migrations ship inside
its package, allowing an installed wheel to migrate a database without a checkout.

## Local configuration

Runtime commands resolve `--config`, then `TOKKEEPER_CONFIG`, then `./tokkeeper.yml`. Initialization writes into the current
or selected directory and refuses to overwrite existing files. Generated configuration and keys are private. Standalone
inference keys and the connected bootstrap key use file references, avoiding an additional environment export before startup.

Relative runtime paths resolve against the configuration file; taxonomy and secret references in a local bundle resolve
against that bundle. Moving the working directory cannot select a different key or state directory. Provider credentials
remain in their selected secret store. Validation checks the configuration and local bundle admission without pretending
to prove upstream connectivity. A connected gateway validates its configuration locally and admits fetched bundles at runtime.

`serve` runs in the foreground. Migration, taxonomy import, fixtures, and owner recovery are explicit commands. The development
control-plane reloader also applies migrations. Containers invoke the same operations through the CLI; their scripts retain
only deployment preparation and process supervision. Containers update through image replacement, not package self-updates.

## Verification

CLI tests exercise initialization, overwrite refusal, error privacy, help without optional runtimes, and configuration
validation. Installation tests build and install wheels into isolated tool environments. They verify the base CLI, live
standalone inference with the gateway extra, and migration plus HTTP serving with the control-plane extra. Import-linter
prevents the runtimes from importing the CLI and continues to enforce data-plane isolation.

See the [CLI reference](../../docs/reference/cli.mdx) for commands and the [standalone guide](../../docs/deployment/gateway.mdx)
for a complete gateway setup.

## Configuration paths

Filesystem settings use the shared `ConfigPath` type. Each file loader supplies its containing directory through
`ConfigContext`, and Pydantic resolves explicit and default paths during validation. Absolute paths stay unchanged.
Loaders return the validated configuration directly; they do not inspect storage variants or copy nested settings to
rewrite paths. New storage implementations declare their path fields using the same type.
