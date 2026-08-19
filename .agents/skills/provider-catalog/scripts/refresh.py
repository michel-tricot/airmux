"""Refresh the catalog in staging and publish only a validated result."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from catalog_io import atomic_write_text
from paths import TAXONOMY

HERE = Path(__file__).resolve().parent


def commands(confirmed: bool) -> list[list[str]]:
    confirmation = ["--yes"] if confirmed else []
    return [
        ["fetch_models.py"],
        ["enrich.py"],
        ["discover_parameters.py"],
        ["discover_capabilities.py"],
        ["smoke.py", *confirmation],
        ["probe_capabilities.py", "--replace", *confirmation],
        ["probe_parameters.py", "--replace", *confirmation],
        ["build_taxonomy.py"],
        ["validate.py"],
    ]


def publish(staged: Path, live: Path) -> None:
    for source in sorted(path for path in staged.rglob("*") if path.is_file()):
        destination = live / source.relative_to(staged)
        atomic_write_text(destination, source.read_text())


def staged_refresh(live: Path, phase_commands: Sequence[Sequence[str]]) -> None:
    with tempfile.TemporaryDirectory(prefix="airllm-taxonomy-") as temporary:
        staged = Path(temporary) / "taxonomy"
        shutil.copytree(live, staged)
        environment = {**os.environ, "AIRLLM_TAXONOMY_ROOT": str(staged)}
        for command in phase_commands:
            print(f"== {' '.join(command)}")
            subprocess.run([sys.executable, str(HERE / command[0]), *command[1:]], check=True, env=environment)
        publish(staged, live)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transactionally refresh and validate the provider catalog")
    parser.add_argument("--yes", action="store_true", help="Confirm probe runs above their request guardrails")
    return parser.parse_args(argv)


def main() -> int:
    arguments = parse_args()
    try:
        staged_refresh(TAXONOMY, commands(arguments.yes))
    except subprocess.CalledProcessError as exc:
        print(f"refresh stopped at {Path(exc.cmd[1]).name}; the live catalog was not changed", file=sys.stderr)
        return exc.returncode or 1
    print("published validated catalog")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
