# AirLLM documentation

# Quickstart

Install Docker with Compose 2.24.4 or newer, clone the repository, and prepare the environment:

```sh
git clone https://github.com/michel-tricot/airllm.git
cd airllm
cp .env.example .env
```

Add one provider key to `.env`, such as `OPENAI_API_KEY`, then run:

```sh
docker compose up -d --build --wait
docker compose run --rm setup
```

Setup creates the owner account, organization, workspace, and inference key. It stores the provider
credential in AirLLM and sends a real inference request before reporting **Ready**. Open
[localhost:8080](http://localhost:8080) for the console.

`docker compose down` stops AirLLM without deleting data. `docker compose down -v` deletes the
database and application state.

# Guides

- [Deploy AirLLM](/docs/deployment/index): Docker, Fly.io, Render, and DigitalOcean
- [Separate services](/docs/deployment/scaling): independent control plane and gateway replicas
- [Develop locally](/docs/development): source setup, checks, and generated clients
- [Data-plane design](/notes/design/DATAPLANE): routing, adapters, and metering
- [Authority model](/notes/design/AUTHORITY): roles and tenant boundaries
- [Provider credentials](/notes/design/BYOK): credential resolution and isolation

The repository's `examples/` directory contains OpenAI and Anthropic SDK examples, streaming,
and tool calls.
