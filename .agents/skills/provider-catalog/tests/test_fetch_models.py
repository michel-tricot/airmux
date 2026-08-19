from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from fetch_models import carry_forward
from sources.base import ModelSource
from sources.fireworks import Fireworks


def test_model_source_fetches_the_configured_url_with_configured_headers(monkeypatch):
    source = ModelSource()
    calls = []
    monkeypatch.setattr(source, "get", lambda url, headers: calls.append((url, headers)) or {"data": []})

    source.fetch("https://catalog.example/models", {"Authorization": "Bearer secret"})

    assert calls == [("https://catalog.example/models", {"Authorization": "Bearer secret"})]


def test_fireworks_pagination_starts_from_the_configured_url(monkeypatch):
    source = Fireworks()
    calls = []
    payloads = iter(
        [
            {"models": [{"name": "one"}], "nextPageToken": "next"},
            {"models": [{"name": "two"}]},
        ]
    )
    monkeypatch.setattr(source, "get", lambda url, headers: calls.append((url, headers)) or next(payloads))

    result = source.fetch("https://catalog.example/models?pageSize=2", {"Authorization": "Bearer secret"})

    assert result == {"models": [{"name": "one"}, {"name": "two"}]}
    assert [url for url, _ in calls] == [
        "https://catalog.example/models?pageSize=2",
        "https://catalog.example/models?pageSize=2&pageToken=next",
    ]


def test_refetch_preserves_secondary_enrichment_but_not_withdrawn_provider_values(tmp_path: Path):
    path = tmp_path / "example.json"
    path.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "id": "secondary",
                        "context_length": 100,
                        "max_output_tokens": 20,
                        "limits_source": "models.dev",
                        "pricing": {"input_per_mtok": 1},
                        "pricing_source": "models.dev",
                    },
                    {
                        "id": "provider",
                        "context_length": 200,
                        "max_output_tokens": 40,
                        "limits_source": "provider",
                        "pricing": {"input_per_mtok": 2},
                        "pricing_source": "provider",
                    },
                ]
            }
        )
    )
    models = [{"id": "secondary"}, {"id": "provider"}]

    carry_forward(path, models)

    assert models[0] == {
        "id": "secondary",
        "context_length": 100,
        "max_output_tokens": 20,
        "limits_source": "models.dev",
        "pricing": {"input_per_mtok": 1},
        "pricing_source": "models.dev",
    }
    assert models[1] == {"id": "provider"}
