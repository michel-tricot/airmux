from __future__ import annotations

import os
import tarfile
import zipfile
from email.parser import BytesParser
from email.policy import default
from pathlib import Path

import pytest


@pytest.fixture
def distributions():
    directory = os.environ.get("AIRMUX_DISTRIBUTION_DIR")
    if directory is None:
        pytest.skip("set AIRMUX_DISTRIBUTION_DIR to test built distributions")
    return sorted(Path(directory).glob("airmux-*"))


def distribution_readme(artifact):
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            metadata_path = next(path for path in archive.namelist() if path.endswith(".dist-info/METADATA"))
            metadata = archive.read(metadata_path)
    else:
        with tarfile.open(artifact) as archive:
            metadata_member = next(member for member in archive.getmembers() if member.name.endswith("/PKG-INFO"))
            metadata_file = archive.extractfile(metadata_member)
            assert metadata_file is not None
            metadata = metadata_file.read()

    readme = BytesParser(policy=default).parsebytes(metadata).get_payload(decode=True)
    assert isinstance(readme, bytes)
    return readme.decode()


def test_published_distributions_use_the_repository_readme(distributions):
    assert distributions
    repository_readme = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")

    assert {distribution_readme(artifact) for artifact in distributions} == {repository_readme}
