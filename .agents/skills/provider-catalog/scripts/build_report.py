"""Render the field support matrix to a self-contained HTML report."""

import json
from pathlib import Path

from paths import TAXONOMY

HERE = TAXONOMY / "reports"
DATA = {i: json.loads((HERE / f"{i}-request-fields.json").read_text()) for i in ("oai", "anthropic")}

HTML = """<title>Completion request field support</title>
<style>
  :root {
    --ground: #FBFBFD; --surface: #FFFFFF; --raised: #F3F4F8;
    --ink: #14161C; --ink-muted: #6A7180; --ink-faint: #9AA0AD;
    --line: #E2E4EC; --line-strong: #CBCFDB;
    --yes-fill: #DCEFE2; --yes-ink: #1F7A4D;
    --no-fill: #F8E3E3; --no-ink: #A63D3D;
    --accent: #3457D5; --accent-soft: #E8ECFB;
    --warn: #8A6410; --warn-soft: #FBF0D8;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --ground: #0E1015; --surface: #161922; --raised: #1E222D;
      --ink: #EDEFF5; --ink-muted: #9BA2B2; --ink-faint: #6B7383;
      --line: #262B38; --line-strong: #394051;
      --yes-fill: #16341F; --yes-ink: #6FCF97;
      --no-fill: #3A1D1D; --no-ink: #E88C8C;
      --accent: #8AA0F5; --accent-soft: #1B2138;
      --warn: #E0B457; --warn-soft: #2E2612;
    }
  }
  :root[data-theme="dark"] {
    --ground: #0E1015; --surface: #161922; --raised: #1E222D;
    --ink: #EDEFF5; --ink-muted: #9BA2B2; --ink-faint: #6B7383;
    --line: #262B38; --line-strong: #394051;
    --yes-fill: #16341F; --yes-ink: #6FCF97;
    --no-fill: #3A1D1D; --no-ink: #E88C8C;
    --accent: #8AA0F5; --accent-soft: #1B2138;
    --warn: #E0B457; --warn-soft: #2E2612;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--ground); color: var(--ink);
    font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 14px; line-height: 1.5;
  }
  .wrap { max-width: 1600px; margin: 0 auto; padding: 40px 28px 80px; display: flex; flex-direction: column; gap: 28px; }
  header { display: flex; flex-direction: column; gap: 10px; }
  h1 { margin: 0; font-size: 26px; font-weight: 620; letter-spacing: -0.02em; text-wrap: balance; }
  .lede { margin: 0; color: var(--ink-muted); max-width: 68ch; }
  .eyebrow { font-size: 11px; letter-spacing: 0.09em; text-transform: uppercase; color: var(--ink-faint); font-weight: 600; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1px; background: var(--line); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
  .stat { background: var(--surface); padding: 14px 16px; display: flex; flex-direction: column; gap: 3px; }
  .stat b { font-size: 24px; font-weight: 620; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
  .stat span { font-size: 12px; color: var(--ink-muted); }
  .controls { display: flex; flex-wrap: wrap; gap: 18px; align-items: center; padding: 12px 16px; background: var(--surface); border: 1px solid var(--line); border-radius: 10px; }
  .seg { display: inline-flex; border: 1px solid var(--line-strong); border-radius: 7px; overflow: hidden; }
  .seg button { appearance: none; border: 0; background: var(--surface); color: var(--ink-muted); font: inherit; font-size: 13px; padding: 6px 14px; cursor: pointer; }
  .seg button[aria-pressed="true"] { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
  .seg button + button { border-left: 1px solid var(--line-strong); }
  label.check { display: inline-flex; gap: 7px; align-items: center; font-size: 13px; color: var(--ink-muted); cursor: pointer; }
  input[type="search"] { font: inherit; font-size: 13px; padding: 6px 10px; border: 1px solid var(--line-strong); border-radius: 7px; background: var(--surface); color: var(--ink); min-width: 200px; }
  button:focus-visible, input:focus-visible, label.check:focus-within { outline: 2px solid var(--accent); outline-offset: 2px; }
  .scroll { overflow: auto; max-height: 76vh; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); }
  table { border-collapse: separate; border-spacing: 0; font-variant-numeric: tabular-nums; }
  th, td { border-bottom: 1px solid var(--line); border-right: 1px solid var(--line); }
  thead th { position: sticky; top: 0; z-index: 3; background: var(--raised); vertical-align: bottom; padding: 8px 4px; font-size: 11px; font-weight: 600; }
  th.rot { height: 132px; white-space: nowrap; }
  th.rot > div { writing-mode: vertical-rl; transform: rotate(180deg); margin: 0 auto; color: var(--ink-muted); }
  th.rot.lead > div { color: var(--accent); font-weight: 700; }
  th.rot.standin > div { color: var(--warn); }
  th.path, td.path { position: sticky; left: 0; z-index: 2; background: var(--surface); text-align: left; padding: 5px 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; white-space: nowrap; }
  thead th.path { z-index: 4; background: var(--raised); font-family: inherit; }
  th.num, td.num { position: sticky; left: var(--pathw); z-index: 2; background: var(--surface); text-align: right; padding: 5px 10px; font-size: 12px; font-weight: 600; min-width: 52px; }
  thead th.num { z-index: 4; background: var(--raised); }
  td.num { border-right: 2px solid var(--line-strong); color: var(--ink-muted); }
  thead th.num { border-right: 2px solid var(--line-strong); }
  td.cell { width: 30px; min-width: 30px; padding: 0; text-align: center; }
  td.yes { background: var(--yes-fill); }
  td.no { background: var(--no-fill); }
  td.cell span { display: block; font-size: 10px; line-height: 26px; }
  td.yes span { color: var(--yes-ink); }
  td.no span { color: var(--no-ink); }
  tbody tr:hover td.path, tbody tr:hover td.num { background: var(--raised); }
  .bar { display: inline-block; height: 4px; border-radius: 2px; background: var(--accent); vertical-align: middle; margin-left: 6px; }
  .notes { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
  .note { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; }
  .note h3 { margin: 0 0 6px; font-size: 13px; font-weight: 620; }
  .note p { margin: 0; font-size: 13px; color: var(--ink-muted); }
  .note code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; background: var(--raised); padding: 1px 4px; border-radius: 3px; }
  .flag { display: inline-block; width: 9px; height: 9px; border-radius: 2px; vertical-align: middle; margin-right: 5px; }
  .empty { padding: 40px; text-align: center; color: var(--ink-muted); }
  @media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
</style>

<div class="wrap">
  <header>
    <div class="eyebrow">airllm taxonomy &middot; completion request surface</div>
    <h1>Which providers accept which request fields</h1>
    <p class="lede">Every JSONPath found in a provider's own published completion request schema, to two levels of nesting. Green means the field appears in that provider's schema; red means it does not. Absence is evidence about the schema, not proof the API rejects the field.</p>
  </header>

  <div class="stats" id="stats"></div>

  <div class="controls">
    <div class="seg" role="group" aria-label="Wire shape">
      <button data-ingress="oai" aria-pressed="true">OpenAI shape</button>
      <button data-ingress="anthropic" aria-pressed="false">Anthropic shape</button>
    </div>
    <input type="search" id="q" placeholder="Filter paths, e.g. tool" aria-label="Filter paths">
    <label class="check"><input type="checkbox" id="shared"> Shared only (2+ providers)</label>
    <label class="check"><input type="checkbox" id="toplevel"> Top level only</label>
    <label class="check"><input type="checkbox" id="hidestandin"> Hide canonical stand-ins</label>
  </div>

  <div class="scroll"><div id="matrix"></div></div>

  <div class="notes">
    <div class="note">
      <h3><span class="flag" style="background:var(--warn)"></span>Canonical stand-ins</h3>
      <p>Six providers publish no request parameters of their own and only state SDK compatibility, so their column restates OpenAI's schema verbatim. Their amber headers are a compatibility claim, not independent evidence. The <code>verified</code> count excludes them.</p>
    </div>
    <div class="note">
      <h3>Why so few universal fields</h3>
      <p>Only <code>$.messages</code>, <code>$.messages[*].role</code>, <code>$.messages[*].content</code> and <code>$.stream</code> appear in all 28. Even <code>$.model</code> misses one: Azure AI Foundry puts the deployment name in the URL, so the body has no model field.</p>
    </div>
    <div class="note">
      <h3>The long tail is mostly one router</h3>
      <p>Most single-provider paths belong to OpenRouter, whose request carries routing controls no upstream provider has. Filtering to shared fields leaves the surface an adapter actually has to reconcile.</p>
    </div>
  </div>
</div>

<script>
const DATA = __DATA__;
let ingress = "oai";

const el = (t, c, txt) => { const n = document.createElement(t); if (c) n.className = c; if (txt != null) n.textContent = txt; return n; };

function activeColumns() {
  const cols = DATA[ingress].columns;
  return document.getElementById("hidestandin").checked ? cols.filter(c => !c.standin) : cols;
}

function activeRows() {
  const d = DATA[ingress];
  const q = document.getElementById("q").value.trim().toLowerCase();
  const sharedOnly = document.getElementById("shared").checked;
  const topOnly = document.getElementById("toplevel").checked;
  const hide = document.getElementById("hidestandin").checked;
  const keep = d.columns.map(c => !hide || !c.standin);

  return d.rows.map(r => {
    const flags = r.flags.filter((_, i) => keep[i]);
    return { path: r.path, flags, total: flags.reduce((a, b) => a + b, 0), verified: r.verified };
  }).filter(r => {
    if (r.total === 0) return false;
    if (q && !r.path.toLowerCase().includes(q)) return false;
    if (sharedOnly && r.total < 2) return false;
    if (topOnly && (r.path.split(".").length !== 2 || r.path.includes("["))) return false;
    return true;
  }).sort((a, b) => b.total - a.total || a.path.localeCompare(b.path));
}

function renderStats() {
  const d = DATA[ingress], cols = activeColumns(), rows = activeRows();
  const universal = rows.filter(r => r.total === cols.length).length;
  const solo = rows.filter(r => r.total === 1).length;
  const stats = [
    [rows.length, "paths shown"],
    [cols.length, "columns"],
    [universal, "accepted by all"],
    [solo, "single provider"],
    [d.columns.filter(c => c.standin).length, "canonical stand-ins"],
  ];
  const host = document.getElementById("stats");
  host.replaceChildren(...stats.map(([n, label]) => {
    const s = el("div", "stat");
    s.append(el("b", null, String(n)), el("span", null, label));
    return s;
  }));
}

function renderMatrix() {
  const cols = activeColumns(), rows = activeRows();
  const host = document.getElementById("matrix");
  if (!rows.length) { host.replaceChildren(el("div", "empty", "No paths match that filter.")); return; }

  const table = el("table");
  const thead = el("thead"), htr = el("tr");
  htr.append(el("th", "path", "JSONPath"), el("th", "num", "n"));
  cols.forEach(c => {
    const th = el("th", "rot" + (c.kind === "router" ? " lead" : "") + (c.standin ? " standin" : ""));
    th.append(el("div", null, c.name + (c.standin ? "  \\u25B3" : "")));
    th.title = c.standin ? c.name + " restates the canonical schema" : c.name;
    htr.append(th);
  });
  thead.append(htr);

  const tbody = el("tbody");
  const max = cols.length;
  rows.forEach(r => {
    const tr = el("tr");
    tr.append(el("td", "path", r.path));
    const num = el("td", "num");
    num.append(document.createTextNode(String(r.total)));
    const bar = el("span", "bar");
    bar.style.width = Math.max(2, Math.round((r.total / max) * 26)) + "px";
    num.append(bar);
    tr.append(num);
    r.flags.forEach((f, i) => {
      const td = el("td", "cell " + (f ? "yes" : "no"));
      td.append(el("span", null, f ? "\\u2713" : "\\u00B7"));
      td.title = cols[i].name + (f ? " accepts " : " does not list ") + r.path;
      tr.append(td);
    });
    tbody.append(tr);
  });

  table.append(thead, tbody);
  host.replaceChildren(table);

  const first = table.querySelector("thead th.path");
  if (first) document.documentElement.style.setProperty("--pathw", first.getBoundingClientRect().width + "px");
}

function render() { renderStats(); renderMatrix(); }

document.querySelectorAll(".seg button").forEach(b => b.addEventListener("click", () => {
  ingress = b.dataset.ingress;
  document.querySelectorAll(".seg button").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  render();
}));
["q", "shared", "toplevel", "hidestandin"].forEach(id =>
  document.getElementById(id).addEventListener("input", render));

render();
</script>
"""


def main() -> int:
    out = HERE / "field-matrix.html"
    out.write_text(HTML.replace("__DATA__", json.dumps(DATA, separators=(",", ":"))))
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
