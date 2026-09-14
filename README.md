# TokKeeper

TokKeeper is a self-hosted LLM gateway. Applications use one endpoint across providers while TokKeeper handles request
translation, workspace policies, scoped provider credentials, inference keys, failover, and usage accounting.

## Architecture

TokKeeper separates mutable management work from the inference request path:

| Plane | Responsibility |
| --- | --- |
| Control plane | Organizations, workspaces, users, credentials, policies, catalog data, bundles, usage, and audit activity |
| Data plane | Inference authentication, canonical translation, policy evaluation, routing, streaming, and metering |

Caller dialects and provider protocols meet at one canonical model. Adding a caller dialect requires one ingress adapter;
adding a provider family requires one egress adapter. Policy, routing, and metering remain provider-neutral and are
evaluated against an immutable configuration bundle instead of querying management state on the request path.

See [Architecture](docs/concepts/architecture.mdx) for the full data flow and failure boundaries.

## Quickstart

You need Docker with Compose 2.24.4+, Python 3.13+, [uv](https://docs.astral.sh/uv/getting-started/installation/), and one provider API key.

```sh
git clone https://github.com/michel-tricot/tokkeeper.git
cd tokkeeper
cp .env.example .env
```

Add a provider key to `.env`, then run:

```sh
docker compose up -d --build --wait
uv run --package cli --no-dev --frozen tokkeeper quickstart --url http://localhost:8080
```

`quickstart` creates or resumes the owner account, organization, and workspace; imports missing provider credentials;
prints a new inference key; and verifies it with a real model request. Open [localhost:8080](http://localhost:8080) for
the console.

## Common commands

| Goal | Command |
| --- | --- |
| Start or update the local stack | `docker compose up -d --build --wait` |
| Check gateway readiness | `curl --fail http://localhost:8080/readyz` |
| Inspect the installation | `uv run --package cli --no-dev --frozen tokkeeper doctor` |
| Follow service logs | `docker compose logs -f tokkeeper` |
| Stop while preserving state | `docker compose down` |
| Validate documentation | `uv run pytest tests/documentation` |

## Documentation

- [Quickstart](docs/quickstart.mdx)
- [Tutorials](docs/guides/openai-sdk.mdx)
- [Features and policies](docs/features/model-routing.mdx)
- [Concepts and architecture](docs/concepts/architecture.mdx)
- [Deployment](docs/deployment/index.mdx)
- [Inference reference](docs/reference/inference.mdx)
- [Management API](docs/reference/management-api.mdx)
- [Development](docs/development.mdx)

The complete management API is generated from [`lib/api-spec/openapi.yaml`](lib/api-spec/openapi.yaml) in the Mintlify reference navigation.

## Contributing

See [Contributing](CONTRIBUTING.md) for the development workflow, architectural boundaries, generated contracts, and
validation expectations. Significant design changes should update the relevant record in
[`notes/design`](notes/design/README.md).

## License and stability

TokKeeper is pre-1.0. APIs, configuration, and migrations may change before the first stable release. Licensed under the [Elastic License 2.0](LICENSE).
