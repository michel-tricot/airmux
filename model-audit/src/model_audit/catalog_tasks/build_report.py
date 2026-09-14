"""Render the field support matrix to a self-contained HTML report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .output import emit
from .paths import TAXONOMY

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(_arguments: Sequence[str] = ()) -> int:
    reports = TAXONOMY / "reports"
    data = {ingress: json.loads((reports / f"{ingress}-request-fields.json").read_text()) for ingress in ("oai", "anthropic")}
    template = Path(__file__).with_name("field_matrix.html").read_text()
    output = reports / "field-matrix.html"
    output.write_text(template.replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    emit(f"wrote {output} ({output.stat().st_size:,} bytes)")
    return 0
