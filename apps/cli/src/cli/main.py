from __future__ import annotations

import base64
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
import typer
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from dotenv import dotenv_values, find_dotenv, load_dotenv, set_key
from pydantic import BaseModel, Field

from contract import (
    BundleV1,
    Catalog,
    KeyEntry,
    ModelEntry,
    ProviderEntry,
    mint_api_token,
    private_key_to_b64,
    public_key_to_b64,
    sign_bundle,
)

app = typer.Typer(name="airllm", no_args_is_help=True)


def _admin_client(control_plane_url: str) -> httpx.Client:
    load_dotenv(find_dotenv(usecwd=True))
    admin_token = os.environ.get("GW_ADMIN_TOKEN")
    if not admin_token:
        typer.echo("GW_ADMIN_TOKEN is not set, run `airllm init` first", err=True)
        raise typer.Exit(1)
    return httpx.Client(base_url=control_plane_url, headers={"authorization": f"Bearer {admin_token}"}, timeout=10.0)


@app.command()
def init(control_plane_url: str = "http://127.0.0.1:8000", cache_dir: str = ".airllm") -> None:
    """Write the shared secrets and wiring for both planes into .env, reusing existing values."""
    cache = Path(cache_dir).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    private_key = _load_or_create_key(cache / "signing.key")
    env_path = Path(".env")
    env_path.touch(exist_ok=True)
    existing = dotenv_values(env_path)
    values = {
        "GW_CONTROL_PLANE_URL": control_plane_url,
        "GW_CACHE_DIR": str(cache),
        "GW_SIGNING_KEY": private_key_to_b64(private_key),
        "GW_BUNDLE_PUBLIC_KEY": public_key_to_b64(private_key.public_key()),
        "GW_ADMIN_TOKEN": existing.get("GW_ADMIN_TOKEN") or secrets.token_urlsafe(24),
        "GW_DP_TOKEN": existing.get("GW_DP_TOKEN") or secrets.token_urlsafe(24),
        "GW_POLL_INTERVAL_S": existing.get("GW_POLL_INTERVAL_S") or "5",
    }
    for k, v in values.items():
        set_key(env_path, k, v)
    typer.echo(f"wrote {env_path.resolve()}")
    typer.echo("next:   uv run control-plane serve --dev")
    typer.echo("        uv run airllm bootstrap")
    typer.echo("        uv run data-plane --dev")


class ProviderSpec(BaseModel):
    provider_id: str
    kind: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    base_url: str
    credential_ref: str


class ModelSpec(BaseModel):
    model_id: str
    provider_id: str
    upstream_model: str = ""
    input_price_per_mtok: float = 0.0
    output_price_per_mtok: float = 0.0
    context_window: int = 128000
    capabilities: list[str] = Field(default_factory=lambda: ["streaming", "tools"])


class KeySpec(BaseModel):
    allowed_models: list[str] = Field(default_factory=lambda: ["*"])


class BootstrapSpec(BaseModel):
    org: str
    providers: list[ProviderSpec] = Field(default_factory=list)
    models: list[ModelSpec] = Field(default_factory=list)
    keys: list[KeySpec] = Field(default_factory=lambda: [KeySpec()])


def _post_expecting(client: httpx.Client, path: str, body: dict, ok: tuple[int, ...]) -> httpx.Response:
    resp = client.post(path, json=body)
    if resp.status_code not in ok:
        typer.echo(f"POST {path} failed: {resp.status_code} {resp.text}", err=True)
        raise typer.Exit(1)
    return resp


@app.command()
def bootstrap(file: str = "bootstrap.yml", control_plane_url: str = "") -> None:
    """Apply a YAML spec (org, providers, models, keys) through the admin API and compile a bundle."""
    path = Path(file)
    if not path.exists():
        typer.echo(f"{file} not found", err=True)
        raise typer.Exit(1)
    spec = BootstrapSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    load_dotenv(find_dotenv(usecwd=True))
    cp_url = control_plane_url or os.environ.get("GW_CONTROL_PLANE_URL", "http://127.0.0.1:8000")
    with _admin_client(cp_url) as c:
        _post_expecting(c, "/admin/orgs", {"id": spec.org}, ok=(200, 409))
        for provider in spec.providers:
            _post_expecting(c, "/admin/providers", {"org_id": spec.org, **provider.model_dump()}, ok=(200, 409))
        for model in spec.models:
            _post_expecting(c, "/admin/models", {"org_id": spec.org, **model.model_dump()}, ok=(200, 409))
        minted = [
            _post_expecting(c, "/admin/keys", {"org_id": spec.org, "allowed_models": key.allowed_models}, ok=(200,)).json() for key in spec.keys
        ]
        compiled = _post_expecting(c, "/admin/bundles/compile", {"org_id": spec.org}, ok=(200,)).json()
    for key in minted:
        typer.echo(f"key {key['key_id']} minted")
    if minted:
        env_path = Path(".env")
        env_path.touch(exist_ok=True)
        set_key(env_path, "AIRLLM_TOKEN", minted[0]["token"])
        typer.echo("first token saved to .env as AIRLLM_TOKEN")
    typer.echo(f"bundle {compiled['bundle_id']} v{compiled['version']} compiled, data plane picks it up within one poll interval")


def _load_or_create_key(key_path: Path) -> Ed25519PrivateKey:
    if key_path.exists():
        loaded = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            typer.echo(f"{key_path} is not an Ed25519 key", err=True)
            raise typer.Exit(1)
        return loaded
    key = Ed25519PrivateKey.generate()
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return key


@app.command()
def seed(  # noqa: PLR0913, PLR0917 CLI options are a flat namespace by design
    cache_dir: str = ".airllm",
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o-mini",
    upstream_model: str = "",
    credential_ref: str = "env:OPENAI_API_KEY",
    write_env: bool = True,
) -> None:
    """Write a signed dev bundle to the data plane cache dir and print a caller token."""
    cache = Path(cache_dir).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    private_key = _load_or_create_key(cache / "signing.key")
    now = datetime.now(tz=UTC)
    bundle = BundleV1(
        bundle_id=uuid4(),
        org_id="org-dev",
        issued_at=now,
        expires_at=now + timedelta(hours=24),
        keys=[KeyEntry(key_id="k-dev", org_id="org-dev", allowed_models=["*"])],
        revocations=[],
        catalog=Catalog(
            providers=[ProviderEntry(provider_id="openai", kind="openai_compatible", base_url=base_url, credential_ref=credential_ref)],
            models=[
                ModelEntry(
                    model_id=model,
                    provider_id="openai",
                    upstream_model=upstream_model or model,
                    input_price_per_mtok=0.0,
                    output_price_per_mtok=0.0,
                    context_window=128000,
                    capabilities=["streaming", "tools"],
                )
            ],
        ),
    )
    signed = sign_bundle(bundle, private_key, "k1")
    (cache / "bundle.json").write_text(signed.model_dump_json(indent=2), encoding="utf-8")
    public_b64 = base64.b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    token = mint_api_token("k-dev", "org-dev", private_key, now)
    if write_env:
        env_path = Path(".env")
        env_path.touch(exist_ok=True)
        for k, v in {"GW_CACHE_DIR": str(cache), "GW_BUNDLE_PUBLIC_KEY": public_b64, "AIRLLM_TOKEN": token}.items():
            set_key(env_path, k, v)
        typer.echo(f"wrote {env_path.resolve()}")
        typer.echo(f"put your provider key there too: {credential_ref.removeprefix('env:')}=sk-...")
    else:
        typer.echo(f"export GW_CACHE_DIR={cache}")
        typer.echo(f"export GW_BUNDLE_PUBLIC_KEY={public_b64}")
        typer.echo(f"export AIRLLM_TOKEN={token}")
    typer.echo("")
    typer.echo("start:  uv run data-plane")
    typer.echo("test:   source .env")
    typer.echo("        curl -s localhost:8080/v1/chat/completions \\")
    typer.echo('          -H "Authorization: Bearer $AIRLLM_TOKEN" -H "Content-Type: application/json" \\')
    typer.echo(f'          -d \'{{"model": "{model}", "messages": [{{"role": "user", "content": "say hi"}}]}}\'')


@app.command("compile")
def compile_bundle(org: str = "org-dev", control_plane_url: str = "") -> None:
    """Recompile and sign the bundle for an org through the control plane."""
    load_dotenv(find_dotenv(usecwd=True))
    cp_url = control_plane_url or os.environ.get("GW_CONTROL_PLANE_URL", "http://127.0.0.1:8000")
    with _admin_client(cp_url) as c:
        resp = c.post("/admin/bundles/compile", json={"org_id": org})
        resp.raise_for_status()
        compiled = resp.json()
    typer.echo(f"bundle {compiled['bundle_id']} v{compiled['version']} compiled")


@app.command()
def verify() -> None:
    raise NotImplementedError


@app.command()
def loadgen() -> None:
    raise NotImplementedError
