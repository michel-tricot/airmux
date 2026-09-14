# TokKeeper gateway

Run TokKeeper's inference gateway as a Python service with a local taxonomy, inference keys, and policies. Docker,
Postgres, the control plane, and the console are not required. Python 3.13 or newer is required.

Build the workspace wheels and install the CLI with its gateway extra:

```bash
uv build --all-packages --wheel
uv tool install --find-links dist './dist/tokkeeper-0.1.0-py3-none-any.whl[gateway]'
```

Initialize against your existing taxonomy file:

```bash
tokkeeper gateway init --taxonomy /path/to/taxonomy.yml --directory gateway
export OPENAI_API_KEY='your-provider-key'
tokkeeper gateway validate --config gateway/tokkeeper.yml
tokkeeper gateway serve --config gateway/tokkeeper.yml
```

The gateway listens on `127.0.0.1:8080`. Call `/inf/v1/chat/completions`, `/inf/v1/responses`, or `/inf/v1/messages`
with the generated inference key from `gateway/.tokkeeper/inference.key`. The model name must match a `model_id` in your taxonomy.

`init` references the taxonomy without copying it and refuses to overwrite existing files. Provider credentials
resolve from environment variables such as `OPENAI_API_KEY`. The default `devnull` event sink discards usage events.

The repository's `docs/deployment/gateway.mdx` describes configuration, taxonomy reloads, and standalone limits.
