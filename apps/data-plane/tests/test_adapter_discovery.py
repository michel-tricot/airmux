from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from contract import ProviderEntry
from data_plane import egress, ingress
from data_plane.egress.openai_compatible import OpenAICompatibleAdapter
from data_plane.ingress.canonical import CanonicalIngress


def adapter_module(module_name: str, base: type, discriminator: str, value: str) -> ModuleType:
    module = ModuleType(module_name)
    adapter = type("Adapter", (base,), {"__module__": module_name, discriminator: value})
    module.__dict__["Adapter"] = adapter
    return module


def duplicate_modules(package: str, base: type, discriminator: str) -> dict[str, ModuleType]:
    return {
        f"{package}.first": adapter_module(f"{package}.first", base, discriminator, "duplicate"),
        f"{package}.second": adapter_module(f"{package}.second", base, discriminator, "duplicate"),
    }


def test_duplicate_egress_kind_fails_discovery(monkeypatch):
    modules = duplicate_modules(egress.__name__, OpenAICompatibleAdapter, "kind")
    monkeypatch.setattr(egress.pkgutil, "iter_modules", lambda _path: [SimpleNamespace(name="first"), SimpleNamespace(name="second")])
    monkeypatch.setattr(egress.importlib, "import_module", modules.__getitem__)

    with pytest.raises(RuntimeError, match="duplicate egress kind 'duplicate'"):
        egress._discover()


def test_duplicate_ingress_dialect_fails_discovery(monkeypatch):
    modules = duplicate_modules(ingress.__name__, CanonicalIngress, "dialect")
    monkeypatch.setattr(ingress.pkgutil, "iter_modules", lambda _path: [SimpleNamespace(name="first"), SimpleNamespace(name="second")])
    monkeypatch.setattr(ingress.importlib, "import_module", modules.__getitem__)

    with pytest.raises(RuntimeError, match="duplicate ingress dialect 'duplicate'"):
        ingress._discover()


def test_the_bundle_contract_does_not_close_the_discovered_adapter_namespace():
    provider = ProviderEntry(provider_id="future", kind="future_family", base_url="https://example.com/v1")

    assert provider.kind == "future_family"


def test_every_discovered_adapter_has_a_black_box_gateway_protocol_fixture():
    protocols_path = Path(__file__).resolve().parents[3] / "tests/gateway/protocols.json"
    protocols = json.loads(protocols_path.read_text())
    assert set(protocols["ingress"]) == set(ingress.REGISTRY), "Add the new caller dialect to the standalone gateway scenarios"
    assert set(protocols["egress"]) == set(egress.REGISTRY), "Add the new provider family to the standalone gateway scenarios"
