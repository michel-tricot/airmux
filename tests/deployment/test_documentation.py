from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_docker_setup_commands_force_an_interactive_terminal():
    commands = [
        command
        for document in (ROOT / "README.md", *(ROOT / "docs").rglob("*.md"))
        for command in re.findall(r"^docker compose .*\brun\b.*\bsetup$", document.read_text(), re.MULTILINE)
    ]

    assert commands
    assert all("-it" in command.split() for command in commands), commands
