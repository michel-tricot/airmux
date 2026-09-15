# TokKeeper

TokKeeper is a self-hosted LLM gateway. One CLI manages remote installations and runs standalone gateways or control
planes locally.

## Install

You need Python 3.13 or newer and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install tokkeeper
tokkeeper --help
```

Start with the [quickstart](https://github.com/michel-tricot/tokkeeper/blob/main/docs/quickstart.mdx) or run a
[gateway without a control plane](https://github.com/michel-tricot/tokkeeper/blob/main/docs/deployment/gateway.mdx).

TokKeeper is pre-1.0. Configuration and APIs may change before the first stable release. It is licensed under the
[Elastic License 2.0](https://github.com/michel-tricot/tokkeeper/blob/main/LICENSE).
