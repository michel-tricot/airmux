# Command line

airmux has one public executable, `airmux`. It manages remote installations and starts local runtimes through
`gateway` and `control-plane` command groups. The CLI owns Typer, help, output, and actionable command errors. Each runtime
owns typed operations and its application factory. Neither runtime imports the CLI, and the planes still share only `contract`.

Shared taxonomy definitions live in `contract` as `ProviderSpec`, `ModelSpec`, and `TaxonomySpec`, so standalone file loading
has no control-plane dependency. Control-plane `ProviderIn`, `ModelIn`, and `TaxonomySpec` retain `RequestModel` inheritance
and reuse those definitions. API responses retain their `RecordOut` models. Sharing file validation does not remove the
request and response boundaries.

## Installation boundary

The `airmux` distribution installs the CLI and both runtimes. One installation supports remote management,
standalone gateways, and control planes without choosing extras. Installation starts no services and does not require
a database. Its wheel contains the `cli`, `api_models`, `contract`, `control_plane`, and `data_plane` import packages.
The corresponding workspace projects remain local development units so their dependencies and boundaries stay explicit.
They are not published or resolved when installing airmux.

The distribution name `airmux` resolves to two different projects: the CLI workspace project in a development checkout
and the published distribution in an installation. Runtime version reporting reads that name, so both must carry the same
version, and the published dependency list must equal the union of the bundled projects' external dependencies. Repository
tests in `tests/documentation` enforce both invariants.

Runtime imports happen only when their commands execute to keep CLI startup fast. Runtime packages remain independent
of the CLI and each other. Control-plane migrations ship inside its package, allowing an installed wheel to migrate a
database without a checkout. The data-plane package ships the generated routing taxonomy so a standalone installation
can initialize without repository files. The taxonomy build writes both the repository projection and the packaged copy.

Shell completion is an explicit `completion` command in the `Goodies` help section. Keeping installation behind a command
avoids permanent root options while making the large resource command tree practical to explore. The command detects the
current shell by default and also accepts an explicit shell for automated setup.

One public distribution avoids exposing the repository decomposition as an installation or release concern. A GitHub
release builds and verifies its wheel and source distribution before publishing them. The release tag must match the public
distribution version, and the installed behavior suite exercises the same artifact users receive.

The container is also one release artifact. It contains the public distribution, console assets, Nginx, and deployment
scripts, and selects `control-plane`, `data-plane`, `console`, or `airmux` at startup. Role selection is not application
configuration. The serving process creates its bootstrap credential and verifies the schema revision. Deployment
orchestration invokes the explicit migration and taxonomy commands from the same image before serving. Administrative CLI
and standalone gateway commands explicitly override the container entry point instead of adding a second command dispatcher
to the role script.

Main CI builds that image once from the validated Python candidate, exercises every topology against it, and publishes the
validated main-branch image under its source commit. The release workflow promotes that digest under the public version;
it does not rebuild the image.

## Local configuration

Runtime commands resolve `--config`, then `AIRMUX_CONFIG`. Gateway commands use `./.airmux/airmux.yml`, falling back to
a shared `./airmux.yml` when the standalone file is absent; control-plane commands use `./airmux.yml`. Gateway
initialization writes into `.airmux` by default; control-plane initialization writes into the current directory. Both accept
an explicit directory and refuse to overwrite existing files.
Generated configuration and keys are private. Standalone inference keys and the connected bootstrap key use file references,
avoiding an additional environment export before startup. Standalone initialization copies the shipped taxonomy unless the
operator supplies an existing file with `--taxonomy`. After writing the files, the CLI reads the complete saved catalog and
selects the first model backed by a provider variable in the current environment, falling back to the first model for a
deterministic walkthrough. It prints the matching provider variable and copyable commands through a real request, referring to
the inference-key file without exposing its value.

Initializers place a `.gitignore` with generated state. It excludes key files, the file secret store, and gateway runtime state
while leaving configuration and taxonomy visible for operators who intentionally version them.

Relative runtime paths resolve against the configuration file; taxonomy and secret references in a local bundle resolve
against that bundle. Moving the working directory cannot select a different key or state directory. Provider credentials
remain in their selected secret store. Validation checks the configuration and local bundle admission without pretending
to prove upstream connectivity. A connected gateway validates its configuration locally and admits fetched bundles at runtime.

`serve` runs in the foreground. Migration, taxonomy import, fixtures, and owner recovery are explicit commands. The control
plane verifies the schema revision before serving in both development and production. Containers invoke the same operations
through the CLI; their role script retains only process supervision. Containers update through image replacement, not package
self-updates.

## Verification

CLI tests exercise initialization, overwrite refusal, error privacy, runtime help, and configuration
validation. Installation tests build and install wheels into isolated tool environments. They verify the installed CLI, live
standalone inference, and control-plane migration plus HTTP serving. Import-linter
prevents the runtimes from importing the CLI and continues to enforce data-plane isolation.

See the [CLI reference](../../docs/reference/cli.mdx) for commands and the [standalone guide](../../docs/deployment/gateway.mdx)
for a complete gateway setup.

## Configuration paths

Filesystem settings use the shared `ConfigPath` type. Each file loader supplies its containing directory through
`ConfigContext`, and Pydantic resolves explicit and default paths during validation. Absolute paths stay unchanged.
Loaders return the validated configuration directly; they do not inspect storage variants or copy nested settings to
rewrite paths. New storage implementations declare their path fields using the same type.
