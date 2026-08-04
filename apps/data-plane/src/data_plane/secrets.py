from __future__ import annotations

import os
from pathlib import Path


class UnsupportedCredentialRefError(Exception):
    def __init__(self, scheme: str) -> None:
        super().__init__(f"unsupported credential_ref scheme: {scheme}")


def resolve(credential_ref: str) -> str:
    scheme, _, rest = credential_ref.partition(":")
    if scheme == "env":
        return os.environ[rest]
    if scheme == "file":
        return Path(rest).read_text(encoding="utf-8").strip()
    raise UnsupportedCredentialRefError(scheme)


def try_resolve(credential_ref: str) -> str | None:
    """The forgiving variant for config refs: missing values become None instead of raising."""
    scheme, _, rest = credential_ref.partition(":")
    if scheme == "env":
        return os.environ.get(rest)
    if scheme == "file":
        ref = Path(rest)
        return ref.read_text(encoding="utf-8").strip() if ref.exists() else None
    raise UnsupportedCredentialRefError(scheme)
