from __future__ import annotations

import json
import platform
import statistics
import timeit
from functools import partial
from pathlib import Path  # noqa: TC003 Typer resolves CLI annotations at runtime
from typing import TYPE_CHECKING, Annotated

import pydantic
import pydantic_core
import typer

from data_plane.canonical import CanonicalRequest, CanonicalTextPart, CanonicalUserMessage
from data_plane.egress.base import encode
from data_plane.formats.openai import ChatBody, UpstreamChunk, body_of

if TYPE_CHECKING:
    from collections.abc import Callable

app = typer.Typer()


def stdlib_encode(body: ChatBody) -> bytes:
    rendered = {"max_tokens" if key == "max_output_tokens" else key: value for key, value in body.items() if value is not None}
    return json.dumps(rendered).encode()


def parse_event(parser: Callable[[bytes], object], payload: bytes) -> UpstreamChunk:
    return UpstreamChunk.model_validate(parser(payload))


@app.command()
def benchmark(
    output: Annotated[Path, typer.Option()],
    iterations: Annotated[int, typer.Option(min=1)] = 2000,
    repeats: Annotated[int, typer.Option(min=1)] = 5,
) -> None:
    operations: list[tuple[str, int, Callable[[], object], Callable[[], object]]] = []
    for size in (2, 262144):
        request = CanonicalRequest(model="model", messages=[CanonicalUserMessage(content=[CanonicalTextPart(text="x" * size)])], max_output_tokens=50)
        body = body_of(request, "upstream-model")
        payload = stdlib_encode(body)
        operations.extend(
            [
                ("request_decode", size, partial(json.loads, payload), partial(pydantic_core.from_json, payload)),
                (
                    "provider_encode",
                    size,
                    partial(stdlib_encode, body),
                    partial(encode, body, aliases={"max_output_tokens": "max_tokens"}, extras={}),
                ),
            ]
        )
    event = b'{"id":"response","choices":[{"index":0,"delta":{"content":"hello"}}]}'
    operations.append(
        ("stream_parse_validate", len(event), partial(parse_event, json.loads, event), partial(parse_event, pydantic_core.from_json, event))
    )
    measurements = []
    for operation, size, baseline, candidate in operations:
        before, after = baseline(), candidate()
        assert (json.loads(before) == json.loads(after)) if isinstance(before, bytes) and isinstance(after, bytes) else before == after
        baseline_us = statistics.median(timeit.repeat(baseline, number=iterations, repeat=repeats)) / iterations * 1_000_000
        candidate_us = statistics.median(timeit.repeat(candidate, number=iterations, repeat=repeats)) / iterations * 1_000_000
        measurements.append(
            {
                "operation": operation,
                "content_bytes": size,
                "baseline_us": baseline_us,
                "candidate_us": candidate_us,
                "saved_us": baseline_us - candidate_us,
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "pydantic": pydantic.__version__,
                "pydantic_core": pydantic_core.__version__,
                "iterations": iterations,
                "repeats": repeats,
                "measurements": measurements,
            },
            indent=2,
        )
        + "\n"
    )
    typer.echo(f"Wrote {output}")


if __name__ == "__main__":
    app()
