"""The bundle: how policy reaches the data plane.

One internal type, two sources. remote polls the control plane and verifies signatures; local
compiles a hand-written file. Both feed holder.admit(), the single admission point, so the
request path never learns the source."""

from __future__ import annotations

from data_plane.bundle.config import BundleConfig, LocalBundleConfig, RemoteBundleConfig
from data_plane.bundle.holder import BundleHolder, BundleSnapshot

__all__ = ["BundleConfig", "BundleHolder", "BundleSnapshot", "LocalBundleConfig", "RemoteBundleConfig"]
