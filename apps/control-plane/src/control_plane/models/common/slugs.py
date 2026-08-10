from __future__ import annotations

import re
from typing import Annotated

from pydantic import StringConstraints

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
SLUG_MAX_LENGTH = 63

Slug = Annotated[str, StringConstraints(pattern=SLUG_PATTERN, max_length=SLUG_MAX_LENGTH)]
"""Lowercase alphanumeric words joined by single hyphens, DNS-label length: what reads well in a URL and a shell."""


def slugify(name: str) -> str:
    """The slug a name reduces to. Empty when the name holds nothing a slug can be made of."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:SLUG_MAX_LENGTH].strip("-")
