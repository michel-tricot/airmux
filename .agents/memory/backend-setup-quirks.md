---
name: Backend setup for local development and Replit
description: Current plane commands, bootstrap authentication, and Replit-specific configuration
---

## Commands and Python

The plane commands are `airmux-control-plane` and `airmux-data-plane`; the management CLI is `airmux`. The workspace requires Python >=3.13. The checked-in `.replit` already selects `python-base-3.13`; installing a Python module is not a routine checkout step.

## Taxonomy path

`uv run airmux-control-plane taxonomy` defaults to `taxonomy.yml`, resolved next to the config file. The repository catalog is `taxonomy/taxonomy.yml`. With the root `airmux.yml`, use `uv run airmux-control-plane taxonomy --file taxonomy/taxonomy.yml`. The Replit backend helper already passes this option.

## Ports

The control-plane command defaults to `127.0.0.1:8000`, matching the Vite proxy default. The Replit helper deliberately uses `127.0.0.1:8101`, and `.replit` already sets `CONTROL_PLANE_URL=http://127.0.0.1:8101` for the console proxy. Loopback binding alone does not guarantee preview routing; see [preview port routing](preview-port-routing.md).

## Replit database URL

`scripts/replit-backend.sh` converts the managed `DATABASE_URL` to asyncpg syntax for the application and derives libpq syntax for `psql`. Keep this normalization in the Replit helper, not generic application configuration.

## Bootstrap token, not signing keys

`uv run airmux-control-plane bootstrap-keygen` creates `.airmux/dataplane.key`, a shared bootstrap authentication token. The root `airmux.yml` reads it through a file reference, and the Replit helper generates it when missing.

Policy bundles are published as JSON. The data plane fetches them using bearer authentication, validates their schema and contents, and caches them. There is no bundle signing or signature verification, no `keygen` command, and no `signing.key`/`signing.pub` setup. Provider reasoning signatures are opaque provider values passed through the adapters, separate from bundle authentication.

## Fixture accounts

Fixtures are for fresh development databases. The helper skips seeding when users already exist. A successful seed prints fixture login credentials; do not store those credentials in memory.
