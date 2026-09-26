from __future__ import annotations

from gateway_harness import INFERENCE_KEY, Gateway


def test_gateway_artifacts_retain_redacted_text_and_skip_binary_files(tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("AIRMUX_GATEWAY_ARTIFACTS", str(artifacts))
    gateway = Gateway(tmp_path / "gateway", "startup")
    gateway.write_files()
    gateway.log.write(f"token={INFERENCE_KEY}\n")
    cache = gateway.directory / ".cache/uv"
    cache.mkdir(parents=True)
    (cache / "interpreter.msgpack").write_bytes(b"\x92\xff")

    gateway.close()

    destination = artifacts / "startup"
    assert (destination / "gateway.log").read_text() == "token=[REDACTED]\n"
    assert "[REDACTED]" in (destination / "bundle.yml").read_text()
    assert not (destination / ".cache").exists()
