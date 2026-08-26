# Provider parity

Provider parity identifies whether an agent observes the same behavior when it talks to a model provider directly and when the identical call hops through AirLLM.

Each experiment uses one declarative case and one client driver. It executes the case against the provider's native surface, executes the case again through a configured running AirLLM data plane, normalizes both responses and classifies the difference.

The project is black-box. It imports neither `data_plane` nor `control_plane` and reaches the gateway only through its public HTTP surface.

## Commands

```bash
uv run airllm-parity cases list
uv run airllm-parity targets list --provider openai
uv run airllm-parity runs plan --provider openai -f table
export AIRLLM_GATEWAY_URL=http://127.0.0.1:8080
export AIRLLM_API_KEY=sk-inf-your-key
uv run airllm-parity runs execute --model openai/gpt-5.1
uv run airllm-parity runs execute --model openai/gpt-5.1 --client http
uv run airllm-parity reports show -f table
```

`runs execute` requires a running data plane configured with the selected catalog model ids. Set its origin with `AIRLLM_GATEWAY_URL` and its inference key with `AIRLLM_API_KEY`, or pass `--gateway-url` and `--gateway-api-key`. The command checks `/readyz` before making a direct provider call and never starts or stops the data plane.

Direct provider credentials load from the repository `.env`. Every experiment makes one direct request and one gateway request. A suspected difference is rerun as a pair once by default, and the report retains every confirmation observation. `--confirmations 0` disables confirmation and `--confirmations N` requests up to five paired confirmations. The 500-request guardrail uses the maximum request count including confirmations.

Requests have a 60-second timeout. Vendor SDK clients disable automatic retries so an unavailable endpoint cannot stall a matrix. Use `--request-timeout SECONDS` to change that bound.

If direct model access or gateway authentication cannot be established for a target, later experiments for that target are recorded as `not_run` instead of repeating a matrix that cannot produce parity evidence.

Reports are written as JSON and self-contained HTML under `provider-parity/reports/`. The directory is ignored because results contain transient vendor output and operational failures.

## Verdicts

- `parity`: both paths have the same normalized protocol behavior, including matching provider rejections
- `gateway_regression`: direct satisfies the case oracle and the gateway path does not, and the difference reproduces when confirmation is enabled
- `gateway_only_success`: the gateway succeeds where the direct path does not
- `different`: both paths complete with a reproduced normalized behavior difference
- `inconclusive`: access, authentication, connection, timeout, or a non-reproducing suspected difference prevented a meaningful conclusion
- `expected_difference`: a non-parity result matches `expected-differences.yml`

Generated text is never compared byte-for-byte. Cases assert stable semantic observations such as tool names, JSON validity, structured values, reasoning presence, finish-reason class, usage presence and response parseability.

The final result separates gateway parity from provider feature support. Matching failures are `✓ parity` and `✗ not supported`; only a behavioral difference between the direct and gateway paths fails parity.

Content cases reserve enough output budget for models that consume completion tokens while reasoning. If a model still reaches the output limit before producing evidence needed by the oracle, the feature result is `not evaluated`, not a false feature failure.

The initial matrix covers text and system messages, multi-turn history, inline image input, output limits, sampling parameters, stop and seed, exposed reasoning, reasoning with tools, single and parallel tools, named tool choice, JSON objects, JSON Schema, and buffered and streamed transport.

## Extending the matrix

Add one YAML file under `cases/` for a new behavior. Keep one behavior per case and combine features only when the interaction is the subject of the case.

Use `--client http` to compare native provider JSON and SSE directly with the same wire dialect through the gateway, without a vendor SDK. Use `--client openai` or `--client anthropic` for vendor SDK compatibility runs.

Add one module under `src/provider_parity/drivers/` for a new client. Subclass `ClientDriver`, declare its supported provider endpoints and implement `execute`. Drivers are discovered automatically, so there is no registry to edit.

The taxonomy supplies targets and per-surface evidence. Parity reports never rewrite taxonomy evidence. Unknown support remains unknown, and unsupported combinations are excluded from the default plan.
Use `--include-unknown` for an observational parameter run whose result must not be mistaken for catalog evidence.
