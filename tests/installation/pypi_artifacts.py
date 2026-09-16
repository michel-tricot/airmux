from __future__ import annotations

import hashlib
import time
from pathlib import Path  # noqa: TC003 Typer resolves command annotations at runtime
from typing import Annotated
from urllib.parse import quote

import httpx
import typer
from pydantic import AnyHttpUrl, BaseModel, Field

app = typer.Typer()


class Digests(BaseModel):
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class PublishedFile(BaseModel):
    filename: str
    url: AnyHttpUrl
    digests: Digests
    yanked: bool


class PublishedRelease(BaseModel):
    urls: list[PublishedFile]


@app.command()
def download(
    version: str,
    candidate: Path,
    destination: Path,
    attempts: Annotated[int, typer.Option(min=1)] = 30,
    interval: Annotated[float, typer.Option(min=0)] = 10,
) -> None:
    artifacts = (*candidate.glob("*.whl"), *candidate.glob("*.tar.gz"))
    if len(artifacts) != 2 or {artifact.suffix for artifact in artifacts} != {".whl", ".gz"}:
        message = "Candidate must contain exactly one wheel and one source distribution"
        raise ValueError(message)
    expected = {artifact.name: hashlib.sha256(artifact.read_bytes()).hexdigest() for artifact in artifacts}
    with httpx.Client(timeout=30) as client:
        for attempt in range(attempts):
            response = client.get(f"https://pypi.org/pypi/airmux/{quote(version, safe='')}/json")
            if response.status_code != 404:
                response.raise_for_status()
                release = PublishedRelease.model_validate(response.json())
                names = {artifact.filename for artifact in release.urls}
                if not names <= expected.keys() or len(names) != len(release.urls):
                    message = "PyPI contains unexpected or duplicate artifacts"
                    raise ValueError(message)
                if names == expected.keys():
                    destination.mkdir(parents=True, exist_ok=False)
                    for artifact in release.urls:
                        if artifact.yanked or artifact.digests.sha256 != expected[artifact.filename]:
                            message = f"PyPI artifact differs from candidate or is yanked: {artifact.filename}"
                            raise ValueError(message)
                        if artifact.url.scheme != "https" or artifact.url.host != "files.pythonhosted.org":
                            message = "Artifact URL must use the PyPI file host over HTTPS"
                            raise ValueError(message)
                        downloaded = client.get(str(artifact.url))
                        downloaded.raise_for_status()
                        if hashlib.sha256(downloaded.content).hexdigest() != expected[artifact.filename]:
                            message = f"Downloaded bytes differ from candidate: {artifact.filename}"
                            raise ValueError(message)
                        (destination / artifact.filename).write_bytes(downloaded.content)
                    return
            if attempt + 1 < attempts:
                time.sleep(interval)
    message = "PyPI did not expose both candidate artifacts before the verification deadline"
    raise TimeoutError(message)


if __name__ == "__main__":
    app()
