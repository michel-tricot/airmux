"""Fetch each provider and router mark as a standalone SVG under taxonomy/icons.

Source is @lobehub/icons-static-svg (MIT), pinned, resolved from the icon_mono and
icon_color slugs in providers.yml and routers.yml. Marks are normalized the same way the
taxonomy/taxonomy.yml documents for its inline copies: sizing attributes and titles dropped so
the consumer controls both, gradient and clip ids namespaced so two marks on one page
cannot collide.

Every entry resolves to both a monochrome and a colour mark. Where a vendor has no colour
variant in the set, icon_color names the monochrome slug, so a consumer can always ask for
either without a null check. Where a vendor has no mark at all, a monogram is generated so
the same holds; those are the only files here not traceable to lobehub.

    uv run python fetch_icons.py
"""

from __future__ import annotations

import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from paths import TAXONOMY

import yaml

ROOT = TAXONOMY
OUT = ROOT / "icons"
VERSION = "1.94.0"
BASE = f"https://unpkg.com/@lobehub/icons-static-svg@{VERSION}/icons"
CTX = ssl.create_default_context()
UA = {"User-Agent": "airllm-taxonomy/1.0"}

ID_ATTRS = ("id", "xlink:href", "href", "fill", "stroke", "clip-path", "mask", "filter")


def normalize(svg: str, slug: str) -> str:
    # drop the sizing and layout the consumer should own, and any title we do not control
    svg = re.sub(r'\s+(?:width|height)="[^"]*"', "", svg, count=2)
    svg = re.sub(r'\s+style="flex:none;line-height:1"', "", svg, count=1)
    svg = re.sub(r"<title>.*?</title>", "", svg, flags=re.S)

    # namespace every locally defined id so marks can share a document
    local_ids = set(re.findall(r'\bid="([^"]+)"', svg))
    for raw in sorted(local_ids, key=len, reverse=True):
        safe = f"airllm-{slug}-{raw}"
        svg = svg.replace(f'id="{raw}"', f'id="{safe}"')
        svg = svg.replace(f"url(#{raw})", f"url(#{safe})")
        svg = svg.replace(f'href="#{raw}"', f'href="#{safe}"')

    return re.sub(r"\s{2,}", " ", svg).strip() + "\n"


MONOGRAM = (
    '<svg viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">'
    '<rect x="2" y="2" width="20" height="20" rx="5" opacity=".16"></rect>'
    '<text x="12" y="16.5" text-anchor="middle" font-family="system-ui,-apple-system,'
    'Segoe UI,Roboto,sans-serif" font-size="12" font-weight="600">{letter}</text></svg>\n'
)


def monogram(slug: str) -> str:
    """A generated stand-in for a vendor with no mark in the icon set."""
    return MONOGRAM.format(letter=slug[0].upper())


def main() -> int:
    OUT.mkdir(exist_ok=True)
    entries = []
    for filename, key in (("providers.yml", "providers"), ("routers.yml", "routers")):
        path = ROOT / filename
        if path.exists():
            entries += [(e["id"], e.get("icon_mono"), e.get("icon_color")) for e in yaml.safe_load(path.read_text())[key]]

    slugs = sorted({s for _, mono, color in entries for s in (mono, color) if s})
    missing = sorted(eid for eid, mono, color in entries if not (mono and color))

    written, failed, generated = [], [], []
    for slug in slugs:
        try:
            raw = urllib.request.urlopen(urllib.request.Request(f"{BASE}/{slug}.svg", headers=UA), timeout=30, context=CTX).read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                (OUT / f"{slug}.svg").write_text(monogram(slug))
                generated.append(slug)
                continue
            failed.append((slug, f"HTTP {e.code}"))
            continue
        except Exception as e:
            failed.append((slug, type(e).__name__))
            continue
        (OUT / f"{slug}.svg").write_text(normalize(raw, slug))
        written.append(slug)

    print(f"  {len(written)} marks written to taxonomy/icons at lobehub {VERSION}")
    if generated:
        print(f"  {len(generated)} generated as a monogram, no mark upstream: {', '.join(generated)}")
    if missing:
        print(f"  entries missing an icon field: {', '.join(missing)}")
    for slug, why in failed:
        print(f"  FAIL {slug}: {why}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
