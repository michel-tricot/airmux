from __future__ import annotations

import hashlib

import httpx
import pytest
from pypi_artifacts import app
from typer.testing import CliRunner


@pytest.fixture
def candidate(tmp_path):
    directory = tmp_path / "candidate"
    directory.mkdir()
    files = {"airmux-0.1.1-py3-none-any.whl": b"wheel", "airmux-0.1.1.tar.gz": b"sdist"}
    for name, content in files.items():
        (directory / name).write_bytes(content)
    return directory, files


def published(files):
    return {
        "urls": [
            {
                "filename": name,
                "url": f"https://files.pythonhosted.org/{name}",
                "digests": {"sha256": hashlib.sha256(content).hexdigest()},
                "yanked": False,
            }
            for name, content in files.items()
        ]
    }


def download(candidate, tmp_path):
    directory, _ = candidate
    return CliRunner().invoke(app, ["0.1.1", str(directory), str(tmp_path / "downloaded"), "--attempts", "2", "--interval", "0"])


def test_download_waits_for_pypi_and_preserves_the_tested_bytes(candidate, tmp_path, respx_mock):
    _, files = candidate
    respx_mock.get("https://pypi.org/pypi/airmux/0.1.1/json").mock(side_effect=[httpx.Response(404), httpx.Response(200, json=published(files))])
    for name, content in files.items():
        respx_mock.get(f"https://files.pythonhosted.org/{name}").respond(content=content)
    result = download(candidate, tmp_path)
    assert result.exit_code == 0, result.output
    assert {path.name: path.read_bytes() for path in (tmp_path / "downloaded").iterdir()} == files


@pytest.mark.parametrize("failure", ["metadata_hash", "download_hash", "extra", "missing", "yanked", "host"])
def test_download_rejects_a_different_or_unavailable_release(candidate, tmp_path, respx_mock, failure):
    _, files = candidate
    metadata = published(files)
    if failure == "metadata_hash":
        metadata["urls"][0]["digests"]["sha256"] = "0" * 64
    elif failure == "extra":
        metadata["urls"].append({**metadata["urls"][0], "filename": "unexpected.whl"})
    elif failure == "missing":
        metadata["urls"].pop()
    elif failure == "yanked":
        metadata["urls"][0]["yanked"] = True
    elif failure == "host":
        metadata["urls"][0]["url"] = "https://example.com/wheel"
    respx_mock.get("https://pypi.org/pypi/airmux/0.1.1/json").respond(json=metadata)
    for name, content in files.items():
        respx_mock.get(f"https://files.pythonhosted.org/{name}").respond(content=b"different" if failure == "download_hash" else content)
    result = download(candidate, tmp_path)
    assert result.exit_code != 0


def test_download_does_not_treat_a_registry_error_as_an_unpublished_version(candidate, tmp_path, respx_mock):
    respx_mock.get("https://pypi.org/pypi/airmux/0.1.1/json").respond(503)
    result = download(candidate, tmp_path)
    assert result.exit_code != 0
    assert isinstance(result.exception, httpx.HTTPStatusError)
