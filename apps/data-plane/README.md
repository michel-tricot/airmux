# TokKeeper gateway

Run TokKeeper's inference gateway as a Python service with a local taxonomy, inference keys, and policies. Docker,
Postgres, the control plane, and the console are not required. Python 3.13 or newer is required.

Build the `contract` and `data-plane` wheels from the same checkout:

```bash
uv build --package contract --wheel
uv build --package data-plane --wheel
uv tool install --with ./dist/contract-0.1.0-py3-none-any.whl ./dist/data_plane-0.1.0-py3-none-any.whl
```

Initialize against your existing taxonomy file:

```bash
tokkeeper-data-plane init --taxonomy /path/to/taxonomy.yml --directory gateway
export TOKKEEPER_INFERENCE_KEY="$(cat gateway/inference.key)"
export OPENAI_API_KEY='your-provider-key'
tokkeeper-data-plane validate --config gateway/tokkeeper.yml
tokkeeper-data-plane serve --config gateway/tokkeeper.yml
```

The gateway listens on `127.0.0.1:8080`. Call `/inf/v1/chat/completions`, `/inf/v1/responses`, or `/inf/v1/messages`
with the generated inference key. The model name must match a `model_id` in your taxonomy.

`init` references the taxonomy without copying it and refuses to overwrite an existing directory. Provider credentials
resolve from environment variables such as `OPENAI_API_KEY`. The default `devnull` event sink discards usage events.

The repository's `docs/deployment/gateway.mdx` describes configuration, taxonomy reloads, and standalone limits.
