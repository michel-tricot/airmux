# TokKeeper gateway

Run TokKeeper's inference gateway as a Python service with a local taxonomy, inference keys, and policies. Docker,
Postgres, the control plane, and the console are not required. Python 3.13 or newer is required.

Install the CLI with the gateway runtime:

```bash
uv tool install tokkeeper
```

Initialize with the shipped taxonomy:

```bash
tokkeeper gateway init --directory gateway
export OPENAI_API_KEY='your-provider-key'
tokkeeper gateway validate --config gateway/tokkeeper.yml
tokkeeper gateway serve --config gateway/tokkeeper.yml
```

The gateway listens on `127.0.0.1:8080`. Call `/inf/v1/chat/completions`, `/inf/v1/responses`, or `/inf/v1/messages`
with the generated inference key from `gateway/.tokkeeper/inference.key`. The model name must match a `model_id` in your taxonomy.

`init` copies the shipped taxonomy to `gateway/taxonomy.yml` and refuses to overwrite existing files. Pass `--taxonomy PATH`
to reference an existing taxonomy without copying it. Provider credentials
resolve from environment variables such as `OPENAI_API_KEY`. The default `devnull` event sink discards usage events.

The repository's `docs/deployment/gateway.mdx` describes configuration, taxonomy reloads, and standalone limits.
