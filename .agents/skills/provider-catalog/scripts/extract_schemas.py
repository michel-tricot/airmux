"""Extract request, response and stream schemas from every provider spec we can reach.

SPECS maps (provider, ingress) to the spec URL and the path within it. Auto-detecting the
completion path is unreliable: specs carry several chat-shaped paths, and the right one
differs per vendor, so it is recorded rather than guessed.

    uv run python extract_schemas.py
"""

import json
import re
import ssl
import urllib.request
from pathlib import Path

import yaml

from canonical import write_catalog, write_schema
from paths import TAXONOMY

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0"}
CTX = ssl.create_default_context()
OUT = TAXONOMY / "schemas" / "completion"
OUT.mkdir(parents=True, exist_ok=True)

# (provider, ingress) -> (spec url, path regex)
SPECS = {
    ("openrouter", "oai"): ("https://openrouter.ai/openapi.json", r"^/chat/completions$"),
    ("openrouter", "anthropic"): ("https://openrouter.ai/openapi.json", r"^/messages$"),
    ("openrouter", "oai_responses"): ("https://openrouter.ai/openapi.json", r"^/responses$"),
    ("openai", "oai"): ("https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml", r"^/chat/completions$"),
    ("openai", "oai_responses"): ("https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml", r"^/responses$"),
    ("anthropic", "anthropic"): ("https://storage.googleapis.com/stainless-sdk-openapi-specs/anthropic/anthropic-891ba7f96c3771e1e3ba6cb37fe8cb6d8615b8a06b6c435d9df66f4aad144bb4.yml", r"^/v1/messages$"),
    ("xai", "oai"): ("https://docs.x.ai/openapi.json", r"^/v1/chat/completions$"),
    ("xai", "anthropic"): ("https://docs.x.ai/openapi.json", r"^/v1/messages$"),
    ("mistral", "oai"): ("https://raw.githubusercontent.com/mistralai/platform-docs-public/main/openapi.yaml", r"^/v1/chat/completions$"),
    ("ai21", "oai"): ("https://api.ai21.com/openapi.json", r"^/studio/v1/chat/completions$"),
    ("moonshot", "oai"): ("https://platform.kimi.ai/docs/openapi.json", r"chat/completions$"),
    ("zai", "oai"): ("https://docs.z.ai/openapi.json", r"chat/completions$"),
    ("together", "oai"): ("https://docs.together.ai/openapi.yaml", r"chat/completions$"),
    ("groq", "oai"): ("https://storage.googleapis.com/stainless-sdk-openapi-specs/groqcloud/groqcloud-debd965baa031e12228c41e538741fa6055bf2813bcd062840a19f84a17cea95.yml", r"chat/completions$"),
    ("cerebras", "oai"): ("https://storage.googleapis.com/stainless-sdk-openapi-specs/cerebras/cerebras-cloud-5471bd6d34fdddff21977458788b979ce93f6b080e11ff0d35777182b6615baa.yml", r"chat/completions$"),
    ("deepinfra", "oai"): ("https://api.deepinfra.com/openapi.json", r"^/v1/chat/completions$"),
    ("deepinfra", "anthropic"): ("https://api.deepinfra.com/openapi.json", r"^/anthropic/v1/messages$"),
    ("nebius", "oai"): ("https://api.tokenfactory.nebius.com/openapi.json", r"chat/completions$"),
    ("azure-foundry", "oai"): ("https://raw.githubusercontent.com/Azure/azure-rest-api-specs/main/specification/cognitiveservices/data-plane/AzureOpenAI/inference/stable/2024-10-21/inference.json", r"chat/completions$"),
    ("cohere", "custom"): ("https://raw.githubusercontent.com/cohere-ai/cohere-developer-experience/main/cohere-openapi.yaml", r"^/v2/chat$"),
    ("perplexity", "custom"): ("https://docs.perplexity.ai/openapi.json", r"^/v1/sonar$"),
    ("replicate", "custom"): ("https://api.replicate.com/openapi.json", r"^/predictions$"),
}

_cache = {}


def fetch(url):
    if url not in _cache:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120, context=CTX).read().decode("utf-8", "replace")
        try:
            _cache[url] = json.loads(raw)
        except json.JSONDecodeError:
            _cache[url] = yaml.safe_load(raw)
    return _cache[url]


def make_collector(doc):
    def resolve(ptr):
        node = doc
        for part in ptr.lstrip("#/").split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node

    def collect(schema, defs, seen):
        if isinstance(schema, list):
            return [collect(i, defs, seen) for i in schema]
        if not isinstance(schema, dict):
            return schema
        if "$ref" in schema and isinstance(schema["$ref"], str) and schema["$ref"].startswith("#/"):
            ptr = schema["$ref"]
            key = re.sub(r"[^A-Za-z0-9_.-]", "_", ptr.lstrip("#/"))
            rest = {k: v for k, v in schema.items() if k != "$ref"}
            if key not in seen:
                seen.add(key); defs[key] = None
                defs[key] = collect(resolve(ptr), defs, seen)
            out = {"$ref": f"#/$defs/{key}"}
            if rest:
                out.update(collect(rest, defs, seen))
            return out
        return {k: collect(v, defs, seen) for k, v in schema.items()}

    return collect


def find_op(doc, path_re):
    for path, item in (doc.get("paths") or {}).items():
        if re.search(path_re, path) and (item or {}).get("post"):
            return path, item["post"]
    return None, None


def body(op, kind):
    if kind == "request":
        content = (op.get("requestBody") or {}).get("content") or {}
        for media in ("application/json", "text/json", "*/*"):
            if media in content and "schema" in content[media]:
                return content[media]["schema"]
        for param in op.get("parameters") or []:
            if param.get("in") == "body" and "schema" in param:
                return param["schema"]
        return None
    ok = None
    for code in ("200", "201", 200, 201):
        if code in (op.get("responses") or {}):
            ok = op["responses"][code]
            break
    if not ok:
        return None
    content = ok.get("content") or {}
    if kind == "response":
        for media in ("application/json", "text/json", "*/*"):
            if media in content and "schema" in content[media]:
                return content[media]["schema"]
        if not content and "schema" in ok:
            return ok["schema"]
    if kind == "stream":
        for media in ("text/event-stream", "application/x-ndjson", "text/plain"):
            if media in content and "schema" in content[media]:
                return content[media]["schema"]
    return None


rows = []
for (provider, ingress), (url, path_re) in SPECS.items():
    try:
        doc = fetch(url)
    except Exception as e:
        rows.append((provider, ingress, f"FETCH FAIL {e}")); continue
    path, op = find_op(doc, path_re)
    if not op:
        rows.append((provider, ingress, "path not found")); continue
    collect = make_collector(doc)
    got = []
    for kind in ("request", "response", "stream"):
        sch = body(op, kind)
        if sch is None:
            continue
        if not ({"properties", "$ref", "oneOf", "anyOf", "allOf", "type", "items"} & set(sch)):
            continue  # declared but empty, e.g. deepinfra's 200
        defs = {}
        root = collect(sch, defs, set())
        out = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
        out.update(root)
        if defs:
            out["$defs"] = defs
        f = OUT / f"{ingress}.{provider}.{kind}.json"
        write_schema(f, out)
        got.append(f"{kind}:{f.stat().st_size // 1024}k")
    rows.append((provider, ingress, ", ".join(got) or "nothing extractable"))

for provider, ingress, note in sorted(rows):
    print(f"  {provider:<14} {ingress:<10} {note}")
