from __future__ import annotations

import re

from tests.documentation.test_documentation import FENCE, ROOT


def code_block(document: str, containing: str) -> str:
    blocks = [match.group("body") for match in FENCE.finditer((ROOT / document).read_text()) if containing in match.group("body")]
    assert len(blocks) == 1, f"{document}: expected one code block containing {containing!r}, found {len(blocks)}"
    return blocks[0]


def cli_reference_commands() -> set[str]:
    reference = (ROOT / "docs/reference/cli.mdx").read_text()
    groups = re.findall(r"^\| `([^`]+)`\s*\| ((?:`[^`]+`(?:, )?\s*)+)\|", reference, re.MULTILINE)
    assert groups
    return {f"airmux {group} {command}" for group, commands in groups for command in re.findall(r"`([^`]+)`", commands)}
