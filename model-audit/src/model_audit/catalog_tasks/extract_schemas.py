"""Extract request, response and stream schemas from every provider spec we can reach.

SPECS maps (provider, ingress) to the spec URL and the path within it. Auto-detecting the
completion path is unreliable: specs carry several chat-shaped paths, and the right one
differs per vendor, so it is recorded rather than guessed.

    uv run tokkeeper-audit providers sync --only schemas
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import yaml

from .canonical import write_schema
from .http import fetch_text
from .output import emit
from .paths import TAXONOMY
from .sources import registry
from .types import is_object, object_list, object_or_empty, string

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from .types import CatalogObject, CatalogValue

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0"}
OUT = TAXONOMY / "schemas" / "completion"

# (provider, ingress) -> (spec url, path regex)
SPECS: dict[tuple[str, str], tuple[str, str]] = {
    ("openrouter", "oai"): ("https://openrouter.ai/openapi.json", r"^/chat/completions$"),
    ("openrouter", "anthropic"): ("https://openrouter.ai/openapi.json", r"^/messages$"),
    ("openrouter", "oai_responses"): ("https://openrouter.ai/openapi.json", r"^/responses$"),
    ("openai", "oai"): ("https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml", r"^/chat/completions$"),
    ("openai", "oai_responses"): ("https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml", r"^/responses$"),
    ("anthropic", "anthropic"): (
        "https://storage.googleapis.com/stainless-sdk-openapi-specs/anthropic/anthropic-891ba7f96c3771e1e3ba6cb37fe8cb6d8615b8a06b6c435d9df66f4aad144bb4.yml",
        r"^/v1/messages$",
    ),
    ("xai", "oai"): ("https://docs.x.ai/openapi.json", r"^/v1/chat/completions$"),
    ("xai", "anthropic"): ("https://docs.x.ai/openapi.json", r"^/v1/messages$"),
    ("mistral", "oai"): ("https://raw.githubusercontent.com/mistralai/platform-docs-public/main/openapi.yaml", r"^/v1/chat/completions$"),
    ("ai21", "oai"): ("https://api.ai21.com/openapi.json", r"^/studio/v1/chat/completions$"),
    ("moonshot", "oai"): ("https://platform.kimi.ai/docs/openapi.json", r"chat/completions$"),
    ("zai", "oai"): ("https://docs.z.ai/openapi.json", r"chat/completions$"),
    ("together", "oai"): ("https://docs.together.ai/openapi.yaml", r"chat/completions$"),
    ("groq", "oai"): (
        "https://storage.googleapis.com/stainless-sdk-openapi-specs/groqcloud/groqcloud-debd965baa031e12228c41e538741fa6055bf2813bcd062840a19f84a17cea95.yml",
        r"chat/completions$",
    ),
    ("cerebras", "oai"): (
        "https://storage.googleapis.com/stainless-sdk-openapi-specs/cerebras/cerebras-cloud-5471bd6d34fdddff21977458788b979ce93f6b080e11ff0d35777182b6615baa.yml",
        r"chat/completions$",
    ),
    ("deepinfra", "oai"): ("https://api.deepinfra.com/openapi.json", r"^/v1/chat/completions$"),
    ("deepinfra", "anthropic"): ("https://api.deepinfra.com/openapi.json", r"^/anthropic/v1/messages$"),
    ("nebius", "oai"): ("https://api.tokenfactory.nebius.com/openapi.json", r"chat/completions$"),
    ("azure-foundry", "oai"): (
        "https://raw.githubusercontent.com/Azure/azure-rest-api-specs/main/specification/cognitiveservices/data-plane/AzureOpenAI/inference/stable/2024-10-21/inference.json",
        r"chat/completions$",
    ),
    ("cohere", "custom"): ("https://raw.githubusercontent.com/cohere-ai/cohere-developer-experience/main/cohere-openapi.yaml", r"^/v2/chat$"),
    ("perplexity", "custom"): ("https://docs.perplexity.ai/openapi.json", r"^/v1/sonar$"),
    ("replicate", "custom"): ("https://api.replicate.com/openapi.json", r"^/predictions$"),
}
_cache: dict[str, CatalogObject] = {}


def _string_keys(value: object) -> object:
    if isinstance(value, list):
        return [_string_keys(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _string_keys(item) for key, item in value.items()}
    return value


def fetch(url: str) -> CatalogObject:
    if url not in _cache:
        raw = fetch_text(url, UA, timeout=120)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = yaml.safe_load(raw)
        document = _string_keys(parsed)
        if not is_object(document):
            message = f"provider schema at {url} is not an object"
            raise ValueError(message)
        _cache[url] = document
    return _cache[url]


def make_collector(document: CatalogObject) -> Callable[[CatalogValue, CatalogObject, set[str]], CatalogValue]:
    def resolve(pointer: str) -> CatalogValue:
        node: CatalogValue = document
        for part in pointer.lstrip("#/").split("/"):
            if not is_object(node):
                message = f"schema pointer {pointer} traverses a non-object"
                raise ValueError(message)
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node

    def collect(schema: CatalogValue, definitions: CatalogObject, seen: set[str]) -> CatalogValue:
        if isinstance(schema, list):
            return [collect(item, definitions, seen) for item in schema]
        if not is_object(schema):
            return schema
        reference = string(schema.get("$ref"))
        if reference is not None and reference.startswith("#/"):
            ptr = reference
            key = re.sub(r"[^A-Za-z0-9_.-]", "_", ptr.lstrip("#/"))
            rest = {k: v for k, v in schema.items() if k != "$ref"}
            if key not in seen:
                seen.add(key)
                definitions[key] = None
                definitions[key] = collect(resolve(ptr), definitions, seen)
            out: CatalogObject = {"$ref": f"#/$defs/{key}"}
            if rest:
                collected = collect(rest, definitions, seen)
                if is_object(collected):
                    out.update(collected)
            return out
        return {key: collect(value, definitions, seen) for key, value in schema.items()}

    return collect


def find_op(document: CatalogObject, path_pattern: str) -> tuple[str | None, CatalogObject | None]:
    for path, value in object_or_empty(document.get("paths")).items():
        operation = object_or_empty(object_or_empty(value).get("post"))
        if re.search(path_pattern, path) and operation:
            return path, operation
    return None, None


def body(operation: CatalogObject, kind: str) -> CatalogValue:  # noqa: PLR0911,PLR0912 provider schema dialects expose bodies in distinct locations
    if kind == "request":
        content = object_or_empty(object_or_empty(operation.get("requestBody")).get("content"))
        for media in ("application/json", "text/json", "*/*"):
            schema = object_or_empty(content.get(media)).get("schema")
            if schema is not None:
                return schema
        for param in object_list(operation.get("parameters")):
            if param.get("in") == "body" and "schema" in param:
                return param["schema"]
        return None
    ok = None
    responses = object_or_empty(operation.get("responses"))
    for code in ("200", "201"):
        if code in responses:
            ok = object_or_empty(responses[code])
            break
    if not ok:
        return None
    content = object_or_empty(ok.get("content"))
    if kind == "response":
        for media in ("application/json", "text/json", "*/*"):
            schema = object_or_empty(content.get(media)).get("schema")
            if schema is not None:
                return schema
        if not content and "schema" in ok:
            return ok["schema"]
    if kind == "stream":
        for media in ("text/event-stream", "application/x-ndjson", "text/plain"):
            schema = object_or_empty(content.get(media)).get("schema")
            if schema is not None:
                return schema
    return None


def modernize_recursion(output: CatalogObject) -> None:
    """Translate draft 2019-09 recursion keywords into their 2020-12 replacements.

    OpenAI's spec marks its self-referential CompoundFilter with `$recursiveAnchor: true`
    and points back at it with `$recursiveRef: "#"`. Both were replaced in 2020-12 by
    `$dynamicAnchor` and `$dynamicRef`, which take a name rather than a boolean, so copying
    them verbatim into a document declaring the 2020-12 metaschema produces a schema that is
    not a valid schema. validate.py catches it; the fix belongs here.

    `$recursiveRef: "#"` resolves against the innermost enclosing anchor, which a flattened
    $defs no longer expresses. That is unambiguous only while the document has exactly one
    anchor, so anything else is left alone for validate.py to report rather than guessed at.
    """
    definitions = object_or_empty(output.get("$defs"))
    anchored = [key for key, node in definitions.items() if is_object(node) and node.get("$recursiveAnchor") is True]
    if len(anchored) != 1:
        return
    name = anchored[0]
    anchored_schema = object_or_empty(definitions[name])
    anchored_schema.pop("$recursiveAnchor")
    anchored_schema["$dynamicAnchor"] = name

    def retarget(node: CatalogValue) -> CatalogValue:
        if isinstance(node, list):
            return [retarget(item) for item in node]
        if not is_object(node):
            return node
        if node.get("$recursiveRef") == "#":
            node = {k: v for k, v in node.items() if k != "$recursiveRef"} | {"$dynamicRef": f"#{name}"}
        return {k: retarget(v) for k, v in node.items()}

    output["$defs"] = retarget(output["$defs"])


def active() -> set[str]:
    """Ids in providers.yml and routers.yml.

    SPECS keeps an entry for every provider whose spec has been located, candidates
    included, because finding the spec is the expensive half of promoting one later. Only
    active ids are written though: a candidate carries no derived data, so extracting its
    schema leaves an orphan that validate.py rejects and someone deletes by hand.
    """
    ids: set[str] = set()
    for filename, key in (("providers.yml", "providers"), ("routers.yml", "routers")):
        path = TAXONOMY / filename
        if path.exists():
            ids |= {entry["id"] for entry in yaml.safe_load(path.read_text())[key]}
    return ids


def extract(document: CatalogObject, operation: CatalogObject, provider: str, ingress: str) -> str:
    collect = make_collector(document)
    acquired: list[str] = []
    for kind in ("request", "response", "stream"):
        schema = body(operation, kind)
        if not is_object(schema) or not ({"properties", "$ref", "oneOf", "anyOf", "allOf", "type", "items"} & set(schema)):
            continue
        definitions: CatalogObject = {}
        root = collect(schema, definitions, set())
        if not is_object(root):
            continue
        output: CatalogObject = {"$schema": "https://json-schema.org/draft/2020-12/schema", **root}
        if definitions:
            output["$defs"] = definitions
            modernize_recursion(output)
        path = OUT / f"{ingress}.{provider}.{kind}.json"
        write_schema(path, output)
        acquired.append(f"{kind}:{path.stat().st_size // 1024}k")
    return ", ".join(acquired) or "nothing extractable"


def main(arguments: Sequence[str] = ()) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    specs = dict(SPECS)
    for source in registry().values():
        for schema in source.schemas:
            specs[(source.provider_id, schema.surface)] = (str(schema.url), schema.path_pattern)

    rows: list[tuple[str, str, str]] = []
    live = active()
    selected = set(arguments)
    for (provider, ingress), (url, path_re) in specs.items():
        if selected and provider not in selected and f"{provider}:{ingress}" not in selected:
            continue
        if provider not in live:
            rows.append((provider, ingress, "candidate, spec recorded but not extracted"))
            continue
        try:
            document = fetch(url)
        except Exception as error:  # noqa: BLE001 provider schema failures are reported per source so the remaining catalog can proceed
            rows.append((provider, ingress, f"FETCH FAIL {error}"))
            continue
        _, operation = find_op(document, path_re)
        if not operation:
            rows.append((provider, ingress, "path not found"))
            continue
        rows.append((provider, ingress, extract(document, operation, provider, ingress)))

    for provider, ingress, note in sorted(rows):
        emit(f"  {provider:<14} {ingress:<10} {note}")
    return 0
