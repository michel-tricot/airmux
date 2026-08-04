from __future__ import annotations

from data_plane.ingress.anthropic import AnthropicIngress
from data_plane.ingress.base import EgressStream, Ingress
from data_plane.ingress.canonical import CanonicalIngress

CANONICAL: Ingress = CanonicalIngress()
ANTHROPIC: Ingress = AnthropicIngress()

__all__ = ["ANTHROPIC", "CANONICAL", "EgressStream", "Ingress"]
