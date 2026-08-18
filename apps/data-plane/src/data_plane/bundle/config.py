from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from contract import Ed25519PublicKeyB64
from data_plane.control_plane_link import ControlPlaneLink


class RemoteBundleConfig(BaseModel):
    """The bundle comes from the control plane: polled, signature-verified, cached on disk."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    kind: Literal["remote"] = "remote"
    control_plane: ControlPlaneLink
    verify_key: Ed25519PublicKeyB64  # the public half of the control plane's signing key; verifies bundle signatures
    cache_dir: Path = Path(".airllm")
    poll_interval_s: float = Field(default=30.0, gt=0)
    heartbeat_interval_s: float = Field(default=30.0, gt=0)


class LocalBundleConfig(BaseModel):
    """The bundle is a file the operator writes, no control plane anywhere."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["local"]
    path: Path
    reload_interval_s: float = Field(default=2.0, gt=0)


BundleConfig = Annotated[RemoteBundleConfig | LocalBundleConfig, Field(discriminator="kind")]
