"""Extract request, response and stream schemas from every provider spec we can reach.

SPECS maps (provider, ingress) to the spec URL and the path within it. Auto-detecting the
completion path is unreliable: specs carry several chat-shaped paths, and the right one
differs per vendor, so it is recorded rather than guessed.

    uv run python extract_schemas.py
"""

import json
import re
import ssl
import sys
import urllib.request

import yaml
from canonical import write_schema
from paths import TAXONOMY

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0"}
CTX = ssl.create_default_context()
OUT = TAXONOMY / "schemas" / "completion"
OUT.mkdir(parents=True, exist_ok=True)

PATHS = {
    ("openrouter", "oai"): r"^/chat/completions$",
    ("openrouter", "anthropic"): r"^/messages$",
    ("openrouter", "oai_responses"): r"^/responses$",
    ("openai", "oai"): r"^/chat/completions$",
    ("openai", "oai_responses"): r"^/responses$",
    ("anthropic", "anthropic"): r"^/v1/messages$",
    ("xai", "oai"): r"^/v1/chat/completions$",
    ("xai", "anthropic"): r"^/v1/messages$",
    ("mistral", "oai"): r"^/v1/chat/completions$",
    ("together", "oai"): r"chat/completions$",
    ("groq", "oai"): r"chat/completions$",
    ("cerebras", "oai"): r"chat/completions$",
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


def spec_document(entry: dict) -> dict:
    url = entry.get("openapi")
    if not isinstance(url, str) or not url.startswith("http"):
        raise ValueError(f"{entry['id']} has no OpenAPI source")
    document = fetch(url)
    if url.endswith(".stats.yml"):
        resolved = document.get("openapi_spec_url") if isinstance(document, dict) else None
        if not isinstance(resolved, str) or not resolved.startswith("http"):
            raise ValueError(f"{entry['id']} SDK metadata has no openapi_spec_url")
        document = fetch(resolved)
    if not isinstance(document, dict):
        raise ValueError(f"{entry['id']} OpenAPI source is not an object")
    return document


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
                seen.add(key)
                defs[key] = None
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


def modernize_recursion(out: dict) -> None:
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
    anchored = [key for key, node in (out.get("$defs") or {}).items() if isinstance(node, dict) and node.get("$recursiveAnchor") is True]
    if len(anchored) != 1:
        return
    name = anchored[0]
    out["$defs"][name].pop("$recursiveAnchor")
    out["$defs"][name]["$dynamicAnchor"] = name

    def retarget(node):
        if isinstance(node, list):
            return [retarget(item) for item in node]
        if not isinstance(node, dict):
            return node
        if node.get("$recursiveRef") == "#":
            node = {k: v for k, v in node.items() if k != "$recursiveRef"} | {"$dynamicRef": f"#{name}"}
        return {k: retarget(v) for k, v in node.items()}

    out["$defs"] = retarget(out["$defs"])


def active() -> dict[str, dict]:
    entries = {}
    for filename, key in (("providers.yml", "providers"), ("routers.yml", "routers")):
        path = TAXONOMY / filename
        if path.exists():
            entries.update({entry["id"]: entry for entry in yaml.safe_load(path.read_text())[key]})
    return entries


def main() -> int:
    rows = []
    failures = 0
    providers = active()
    selected = set(sys.argv[1:])
    known = set(providers) | {f"{provider}:{ingress}" for provider, ingress in PATHS}
    if unknown := selected - known:
        print(f"unknown schema targets: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    for (provider, ingress), path_re in PATHS.items():
        if selected and provider not in selected and f"{provider}:{ingress}" not in selected:
            continue
        try:
            doc = spec_document(providers[provider])
        except (OSError, ValueError, yaml.YAMLError) as exc:
            rows.append((provider, ingress, f"fetch failed: {exc}"))
            failures += 1
            continue
        _, operation = find_op(doc, path_re)
        if not operation:
            rows.append((provider, ingress, "path not found"))
            failures += 1
            continue
        collect = make_collector(doc)
        got = []
        for kind in ("request", "response", "stream"):
            schema = body(operation, kind)
            if schema is None or not ({"properties", "$ref", "oneOf", "anyOf", "allOf", "type", "items"} & set(schema)):
                continue
            definitions = {}
            root = collect(schema, definitions, set())
            output = {"$schema": "https://json-schema.org/draft/2020-12/schema", **root}
            if definitions:
                output["$defs"] = definitions
                modernize_recursion(output)
            path = OUT / f"{ingress}.{provider}.{kind}.json"
            write_schema(path, output)
            got.append(f"{kind}:{path.stat().st_size // 1024}k")
        note = ", ".join(got) or "nothing extractable"
        failures += not got
        rows.append((provider, ingress, note))
    for provider, ingress, note in sorted(rows):
        print(f"  {provider:<14} {ingress:<14} {note}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
