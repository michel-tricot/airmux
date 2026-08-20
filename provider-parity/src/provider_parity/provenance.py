from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

from provider_parity.models import RunMetadata


def _git_commit(root: Path) -> str:
    marker = root / ".git"
    if marker.is_dir():
        git = marker
    else:
        value = marker.read_text(encoding="utf-8").strip()
        git = Path(value.removeprefix("gitdir: "))
    head = (git / "HEAD").read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return head
    common = (git / "commondir").read_text(encoding="utf-8").strip() if (git / "commondir").exists() else "."
    return (git / common / head.removeprefix("ref: ")).resolve().read_text(encoding="utf-8").strip()


def _taxonomy_fingerprint(root: Path) -> str:
    paths = [root / "taxonomy" / "providers.yml", root / "taxonomy" / "taxonomy.yml", *sorted((root / "taxonomy" / "models").glob("*.json"))]
    digest = sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:20]


def metadata(root: Path, run_id: str, gateway_url: str) -> RunMetadata:
    return RunMetadata(
        run_id=run_id,
        created_at=datetime.now(tz=UTC).isoformat(),
        harness_commit=_git_commit(root),
        gateway_url=gateway_url,
        taxonomy_fingerprint=_taxonomy_fingerprint(root),
        sdk_versions={"anthropic": version("anthropic"), "openai": version("openai")},
    )
