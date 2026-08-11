"""Locate the catalog no matter where a script is invoked from.

The scripts live with the skill and the data lives in the repo, so neither can assume the
other is a sibling. Walk up for the repo root and take taxonomy/ from there.
"""

from pathlib import Path


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("no repository root above " + str(here))


TAXONOMY = repo_root() / "taxonomy"
