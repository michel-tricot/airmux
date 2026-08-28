from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path

import pytest
import yaml

from model_audit.cases import coverage, load_cases, load_features
from model_audit.models import Case, Oracle, Request
from tests.helpers import case

ROOT = Path(__file__).resolve().parents[1]


def _embedded_data(audit_case: Case) -> bytes:
    content = audit_case.request.messages[0].get("content")
    assert isinstance(content, list)
    block = content[1]
    assert isinstance(block, dict)
    data = block.get("data")
    assert isinstance(data, str)
    return base64.b64decode(data)


def test_case_matrix_covers_every_required_feature():
    features = load_features(ROOT / "definitions" / "features.yml")
    cases = load_cases(ROOT / "cases", features)

    result = coverage(cases, features)

    assert result.missing == ()
    assert result.missing_endpoint_coverage == ()
    assert result.unmapped_request_fields == ()
    assert result.case_count >= 25
    assert "option:parallel_tool_calls" in result.covered
    assert "modality:input_pdf" in result.covered
    assert "interaction:streaming+tools" in result.covered


def test_pdf_input_is_required_and_exercised_on_every_completion_surface():
    features = load_features(ROOT / "definitions" / "features.yml")
    cases = load_cases(ROOT / "cases", features)
    pdf_feature = next(feature for feature in features.features if feature.name == "input_pdf")
    pdf_case = next(case for case in cases if case.id == "modalities.pdf")

    assert set(pdf_feature.endpoints) == {"chat/completions", "responses", "messages"}
    assert pdf_case.applies_to.endpoints == frozenset()


def test_case_ids_and_claims_are_stable_and_auditable():
    features = load_features(ROOT / "definitions" / "features.yml")
    cases = load_cases(ROOT / "cases", features)

    assert len({case.id for case in cases}) == len(cases)
    assert all(case.version == 2 and case.oracle.has_assertion and case.claims for case in cases)


def test_cases_have_room_for_reasoning_models():
    features = load_features(ROOT / "definitions" / "features.yml")
    cases = load_cases(ROOT / "cases", features)

    assert [audit_case.id for audit_case in cases if audit_case.request.max_tokens < 1024] == []


def test_embedded_media_matches_its_semantic_oracle():
    features = load_features(ROOT / "definitions" / "features.yml")
    cases = load_cases(ROOT / "cases", features)
    image_case = next(case for case in cases if case.id == "modalities.image")
    pdf_case = next(case for case in cases if case.id == "modalities.pdf")
    image = _embedded_data(image_case)
    pdf = _embedded_data(pdf_case)
    width, height = struct.unpack(">II", image[16:24])
    position = 8
    compressed = bytearray()
    while position < len(image):
        length = struct.unpack(">I", image[position : position + 4])[0]
        kind = image[position + 4 : position + 8]
        if kind == b"IDAT":
            compressed.extend(image[position + 8 : position + 8 + length])
        position += 12 + length
    scanlines = zlib.decompress(compressed)
    pixels = b"".join(scanlines[offset + 1 : offset + 1 + width * 3] for offset in range(0, len(scanlines), width * 3 + 1))

    assert pixels == b"\xff\x00\x00" * width * height
    assert b"(COBALT)" in pdf


@pytest.mark.parametrize(
    ("block_type", "media_type", "payload", "error"),
    [
        ("image", "image/png", b"not a png", "invalid PNG"),
        ("document", "application/pdf", b"not a pdf", "invalid PDF"),
    ],
)
def test_case_loading_rejects_malformed_embedded_media(tmp_path, block_type, media_type, payload, error):
    invalid = case(
        id=f"modalities.invalid-{block_type}",
        request=Request(
            messages=(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Inspect this fixture"},
                        {"type": block_type, "media_type": media_type, "data": base64.b64encode(payload).decode()},
                    ],
                },
            )
        ),
    )
    (tmp_path / "invalid.yml").write_text(yaml.safe_dump(invalid.model_dump(mode="json")), encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        load_cases(tmp_path)


def test_case_loading_validates_media_in_follow_up_requests(tmp_path):
    invalid = case(
        id="modalities.invalid-follow-up",
        follow_up=Request(
            messages=(
                {
                    "role": "user",
                    "content": [{"type": "image", "media_type": "image/png", "data": base64.b64encode(b"not a png").decode()}],
                },
            )
        ),
    )
    (tmp_path / "invalid.yml").write_text(yaml.safe_dump(invalid.model_dump(mode="json")), encoding="utf-8")

    with pytest.raises(ValueError, match=r"follow-up.*invalid PNG"):
        load_cases(tmp_path)


def test_case_loading_rejects_oracles_for_undeclared_tools(tmp_path):
    invalid = case(id="tools.invalid-oracle", oracle=Oracle(tool_names=("missing_tool",)))
    (tmp_path / "invalid.yml").write_text(yaml.safe_dump(invalid.model_dump(mode="json")), encoding="utf-8")

    with pytest.raises(ValueError, match="expects undeclared tools: missing_tool"):
        load_cases(tmp_path)
