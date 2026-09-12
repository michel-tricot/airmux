# AirLLM

AirLLM is a self-hosted LLM gateway. Applications use one endpoint across providers while AirLLM handles request
translation, workspace policies, scoped provider credentials, inference keys, failover, and usage accounting.

## Quickstart

You need Docker with Compose 2.24.4+, Python 3.13+, [uv](https://docs.astral.sh/uv/getting-started/installation/), and one provider API key.

```sh
git clone https://github.com/michel-tricot/airllm.git
cd airllm
cp .env.example .env
```

Add a provider key to `.env`, then run:

```sh
docker compose up -d --build --wait
uv run --package cli --no-dev --frozen airllm quickstart --url http://localhost:8080
```

`quickstart` creates or resumes the owner account, organization, and workspace; imports missing provider credentials;
prints a new inference key; and verifies it with a real model request. Open [localhost:8080](http://localhost:8080) for
the console.

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

## License and stability

AirLLM is pre-1.0. APIs, configuration, and migrations may change before the first stable release. Licensed under the [Elastic License 2.0](LICENSE).
