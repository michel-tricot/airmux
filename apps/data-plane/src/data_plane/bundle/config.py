from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from contract import Ed25519PublicKeyB64


class RemoteBundleConfig(BaseModel):
    """The bundle comes from the control plane: polled, signature-verified, cached on disk."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    kind: Literal["remote"] = "remote"
    public_key: Ed25519PublicKeyB64  # parsed once from base64 at load; verifies bundle signatures
    org: UUID | None = None  # which org's bundle this data plane serves; None takes the newest across orgs
    cache_dir: Path = Path(".airllm")
    staleness_policy: Literal["serve_and_warn", "refuse"] = "serve_and_warn"
    poll_interval_s: float = 30.0


class LocalBundleConfig(BaseModel):
    """The bundle is a file the operator writes, no control plane anywhere."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["local"]
    path: Path
    reload_interval_s: float = 2.0


BundleConfig = Annotated[RemoteBundleConfig | LocalBundleConfig, Field(discriminator="kind")]
"""Where the bundle comes from, tagged by kind so each source parses only its own settings."""
