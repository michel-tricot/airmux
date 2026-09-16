# airmux gateway

Run airmux's inference gateway as a Python service with a local taxonomy, inference keys, and policies. Docker,
Postgres, the control plane, and the console are not required. Python 3.13 or newer is required.

Install the CLI with the gateway runtime:

```bash
uv tool install airmux
```

Initialize with the shipped taxonomy:

```bash
export OPENAI_API_KEY='your-provider-key'
airmux gateway init
airmux gateway validate
airmux gateway serve
```

The gateway listens on `127.0.0.1:8080`. Call `/inf/v1/chat/completions`, `/inf/v1/responses`, or `/inf/v1/messages`
with the generated inference key from `.airmux/inference.key`. The model name must match a `model_id` in your taxonomy.

The standalone gateway copies the shipped taxonomy to `.airmux/taxonomy.yml` and ignores usage events. Pass
`--taxonomy PATH` to reference an existing taxonomy instead. Provider credentials resolve from environment variables such as
`OPENAI_API_KEY`.

The repository's `docs/deployment/gateway.mdx` describes configuration, taxonomy reloads, and standalone limits.
