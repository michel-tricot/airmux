"""The bundle: how policy reaches the data plane.

One internal type, two sources. remote polls the control plane and verifies signatures; local
compiles a hand-written file. Both feed holder.admit(), the single admission point, so the
request path never learns the source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.bundle.base import BundleSource
from data_plane.bundle.config import BundleConfig, LocalBundleConfig, RemoteBundleConfig
from data_plane.bundle.holder import BundleHolder, BundleSnapshot
from data_plane.bundle.local import LocalBundleSource
from data_plane.bundle.remote import RemoteBundleSource

if TYPE_CHECKING:
    import httpx

    from data_plane.config import ControlPlaneLink

__all__ = ["BundleConfig", "BundleHolder", "BundleSnapshot", "BundleSource", "LocalBundleConfig", "RemoteBundleConfig", "build_bundle_source"]


def build_bundle_source(
    config: BundleConfig,
    control_plane: ControlPlaneLink | None,
    holder: BundleHolder,
    http_client: httpx.AsyncClient,
) -> BundleSource:
    if isinstance(config, LocalBundleConfig):
        return LocalBundleSource(config, holder)
    if control_plane is None:
        msg = "remote bundle requires a control plane"
        raise ValueError(msg)
    return RemoteBundleSource(control_plane, config, holder, http_client)
