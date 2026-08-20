# Provider parity

Provider parity identifies whether an agent observes the same behavior when it talks to a model provider directly and when the identical SDK call hops through AirLLM.

Each experiment uses one declarative case and one vendor SDK driver. It executes the case against the provider's native surface, executes the case again through a configured running AirLLM data plane, normalizes both SDK responses and classifies the difference.

The project is black-box. It imports neither `data_plane` nor `control_plane` and reaches the gateway only through its public HTTP surface.

## Commands

```bash
uv run airllm-parity cases list
uv run airllm-parity targets list --provider openai
uv run airllm-parity runs plan --provider openai -f table
export AIRLLM_GATEWAY_URL=http://127.0.0.1:8080
export AIRLLM_API_KEY=sk-inf-your-key
uv run airllm-parity runs execute --model openai/gpt-5.1
uv run airllm-parity reports show -f table
```

`runs execute` requires a running data plane configured with the selected catalog model ids. Set its origin with `AIRLLM_GATEWAY_URL` and its inference key with `AIRLLM_API_KEY`, or pass `--gateway-url` and `--gateway-api-key`. The command checks `/readyz` before making a direct provider call and never starts or stops the data plane.

Direct provider credentials load from the repository `.env`. A plan above 500 HTTP requests requires `--yes`. Every experiment makes two completion requests, one direct and one through the gateway.

Reports are written as JSON and self-contained HTML under `provider-parity/reports/`. The directory is ignored because results contain transient vendor output and operational failures.

## Verdicts

- `parity`: both paths satisfy the case oracle and their normalized protocol behavior agrees
- `gateway_regression`: direct satisfies the oracle and the gateway path does not
- `provider_limitation`: both paths explicitly report unsupported behavior
- `upstream_failure`: both paths fail in the same outcome class
- `gateway_only_success`: the gateway succeeds where the direct path does not
- `different`: both paths complete but their normalized behavior differs
- `inconclusive`: transport or authentication prevented a meaningful comparison, including gateway 401 and 403 responses
- `expected_difference`: a non-parity result matches `expected-differences.yml`

Generated text is never compared byte-for-byte. Cases assert stable semantic observations such as tool names, JSON validity, structured values, reasoning presence, finish-reason class, usage presence and SDK parseability.

The initial matrix covers text and system messages, multi-turn history, inline image input, output limits, sampling parameters, stop and seed, exposed reasoning, reasoning with tools, single and parallel tools, named tool choice, JSON objects, JSON Schema, and buffered and streamed transport.

## Extending the matrix

Add one YAML file under `cases/` for a new behavior. Keep one behavior per case and combine features only when the interaction is the subject of the case.

Add one module under `src/provider_parity/drivers/` for a new SDK. Subclass `SDKDriver`, declare its supported provider endpoints and implement `execute`. Drivers are discovered automatically, so there is no registry to edit.

The taxonomy supplies targets and per-surface evidence. Parity reports never rewrite taxonomy evidence. Unknown support remains unknown, and unsupported combinations are excluded from the default plan.
Use `--include-unknown` for an observational parameter run whose result must not be mistaken for catalog evidence.
