# Gateway-only onboarding verification

Issue: [#370](https://github.com/michel-tricot/airmux/issues/370)

Tested on 2026-09-25 and 2026-09-26 against commit
`27087ee8e74e2f2795b98f979b282a30e2f9c3aa` (the 0.2.4 release preparation commit), with the guide and test changes in this branch.
The environment was macOS on Apple Silicon, uv 0.8.22, and CPython 3.13.7.

## Observed results

| Check | Result |
| --- | --- |
| Fresh source tree and virtual environment, `uv sync --package airmux --frozen` | Passed |
| `uv run airmux gateway init` and `uv run airmux gateway validate` | Passed with new local state |
| `uv run airmux gateway serve --port 18082` | Started without starting Postgres or a control plane |
| `GET /readyz` on the fresh installation | HTTP 200, `{"status":"ready"}` |
| Unauthenticated inference on the fresh installation | HTTP 401 |
| Documented authenticated buffered request against a running gateway and local test upstream | Passed, response text matched |
| Documented authenticated streaming request against a running gateway and local test upstream | Passed, text matched and stream ended with `[DONE]` |
| Documentation and local guide acceptance tests | 148 passed |
| Ruff and `ty check` | Passed |
| Container build and requests against this commit | Incomplete: session interrupted during build; subsequent Docker daemon requests did not return |
| Real-provider buffered and streaming requests | Incomplete: no provider credential was available |

The clean source tree was extracted with `git archive HEAD`; cloning from GitHub was not part of the installation check.
The local port was changed to avoid other development services. The test upstream verifies HTTP behavior and authentication,
but does not verify provider credentials or external connectivity.

## Repairs

- Added the missing container recipe and a streaming request to the gateway-only guide
- Fixed the local guide test leaving a trailing `uv run` when it split the initialization and serve commands
- Added streaming response assertions to the guide acceptance test
- Fixed the container test replacing the configured image with an unbuilt random image tag

## Remaining verification

Restore Docker, build this checkout, and run:

```bash
docker build -t airmux:issue-370 .
DEPLOYMENT_IMAGE=airmux:issue-370 uv run --all-packages --group dev pytest tests/deployment/test_gateway_container.py -q
```

Then run the guide's local and container setups with a real provider key and record buffered and streaming results.
Issue #370 remains incomplete until both checks pass.
