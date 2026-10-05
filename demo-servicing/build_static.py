"""
Builds a server-free copy of the demo for hosting as a single page (for
example a Claude Artifact). The ledger, month-end math, drafts and compliance
verdicts are precomputed here and embedded in the page; Review decisions and
Outbox approvals then live in the viewer's browser only.

    python build_static.py        -> dist/index.html plus dist/binder/*.pdf

The local app (./run.sh) stays the full version with live recomputation and
the Re-run Extraction call.
"""
import base64
import html
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STATE_DIR", "/tmp/rolledco-build")

from fastapi.testclient import TestClient  # noqa: E402

from app.server import app  # noqa: E402

DIST = ROOT / "dist"
STATIC = ROOT / "app" / "static"

client = TestClient(app)
client.post("/api/reset", json={})
state = client.get("/api/state").json()
summary = client.get("/summary").text
verdicts = {o["id"]: client.post("/api/schedule-payment", json={"obligation_id": o["id"]}).json()
            for o in state["obligations"]}

# ---------------------------------------------------------------- css
css = (STATIC / "styles.css").read_text()
for name in ("BarlowCondensed-Bold.woff2", "Inter-Variable.woff2"):
    b64 = base64.b64encode((STATIC / "fonts" / name).read_bytes()).decode()
    css = css.replace(f'url("/static/fonts/{name}")', f'url("data:font/woff2;base64,{b64}")')
css = css.replace(".shell { display: flex; height: 100vh; overflow: hidden; }",
                  ".shell { display: flex; height: 100%; overflow: hidden; }")
css = css.replace('html, body { height: 100%; margin: 0; }',
                  'html, body { height: 100%; margin: 0; } :root { color-scheme: light; }')
css += """
/* narrow screens: nav becomes a top bar, panels stack, the timeline scrolls sideways */
@media (max-width: 900px) {
  .shell { flex-direction: column; height: auto; overflow: visible; }
  .nav { width: auto; border-right: 0; border-bottom: 1px solid var(--ink-12); padding: 16px 0 0; }
  .nav-list { display: flex; flex-wrap: wrap; margin: 6px 0 0; }
  .nav-item { width: auto; padding: 8px 14px; border-left: 0; border-bottom: 3px solid transparent; }
  .nav-item.active { border-bottom-color: var(--crimson); }
  .nav-deal { padding: 12px 16px 10px; border-bottom: 0; }
  .wordmark { padding: 0 16px; font-size: 28px; }
  .nav-foot { margin-top: 0; padding: 8px 16px 10px; border-top: 0; display: flex; gap: 14px; }
  .topbar { flex-direction: column; align-items: flex-start; gap: 10px; padding: 16px; }
  .content { padding: 16px; overflow: visible; }
  .footer { padding: 0 16px; height: auto; padding-block: 10px; }
  .binder-layout, .monitor-grid, .stats, .seller-cards { grid-template-columns: 1fr; }
  .monitor-grid .span2 { grid-column: auto; }
  .drawer { width: 100%; }
  .timeline-wrap { overflow-x: auto; }
  svg.timeline { min-width: 980px; }
  .card { overflow-x: auto; }
  .stat-list[style] { columns: 1 !important; }
  .content, .main, .shell > * { min-width: 0; }
  .binder-layout > *, .monitor-grid > *, .stats > *, .seller-cards > *, .row > *, .row-between > * { min-width: 0; }
  .summary-chips, .topbar-right, .legend, .timeline-head, .row, .row-between, .draft-head, .sec-head, .nav-foot { flex-wrap: wrap; }
  .chip, .status-pill { white-space: normal; }
  .drawer-backdrop, .drawer { max-width: 100vw; }
  .tip { max-width: 90vw; }
}
"""

# ---------------------------------------------------------------- js
js = (STATIC / "app.js").read_text()
js = js.replace('  async function api(path, body) {\n    const r = await fetch(path,',
                '  async function api(path, body) {\n    if (window.StaticApi) return window.StaticApi(path, body);\n    const r = await fetch(path,')
js = js.replace('href="/binder/', 'href="binder/')
assert "StaticApi" in js and 'href="binder/' in js

shim = r"""
(function () {
  const BASE = window.__ROLLEDCO__;
  const KEY = "rolledco-demo-state";
  let local = { review: {}, outbox: {} };
  try { const raw = localStorage.getItem(KEY); if (raw) local = JSON.parse(raw); } catch (e) {}
  function persist() { try { localStorage.setItem(KEY, JSON.stringify(local)); } catch (e) {} }
  const clone = x => JSON.parse(JSON.stringify(x));
  function addMonths(iso, n) { const [y, m, d] = iso.split("-").map(Number); const dt = new Date(y, m - 1 + n, 1); const last = new Date(dt.getFullYear(), dt.getMonth() + 1, 0).getDate(); dt.setDate(Math.min(d, last)); return dt.toISOString().slice(0, 10); }
  function shiftDays(iso, days) { const [y, m, d] = iso.split("-").map(Number); const dt = new Date(Date.UTC(y, m - 1, d + days)); return dt.toISOString().slice(0, 10); }
  function daysBetween(a, b) { return Math.round((Date.UTC(...b.split("-").map((v, i) => i === 1 ? v - 1 : +v)) - Date.UTC(...a.split("-").map((v, i) => i === 1 ? v - 1 : +v))) / 86400000); }

  function compute() {
    const s = clone(BASE.state);
    const today = s.today;
    const rejected = new Set(Object.keys(local.review).filter(id => local.review[id].decision === "reject"));
    s.obligations.forEach(o => {
      const r = local.review[o.id] || {};
      o.review = { decision: r.decision || null, edits: r.edits };
      if (r.edits) {
        if (r.edits.counterparty) o.counterparty = r.edits.counterparty;
        if (r.edits.amount != null) o.amount = r.edits.amount;
        if (r.edits.amount_each != null) o.schedule.amount_each = r.edits.amount_each;
        if (r.edits.first_date) { o.schedule.first_date = r.edits.first_date; o.next_date = r.edits.first_date; }
      }
    });
    s.ledger.rows = s.ledger.rows.filter(r => !rejected.has(r.id));
    s.ledger.rows.forEach(row => {
      const r = local.review[row.id] || {};
      if (!r.edits) return;
      if (r.edits.counterparty) row.counterparty = r.edits.counterparty;
      if (r.edits.first_date && row.events.length) {
        const delta = daysBetween(row.events[0].date, r.edits.first_date);
        row.events.forEach(e => e.date = shiftDays(e.date, delta));
      }
      if (r.edits.amount_each != null) row.events.forEach(e => { if (e.kind === "payment") e.amount = r.edits.amount_each; });
      row.events.forEach(e => e.counterparty = row.counterparty);
    });
    const all = s.ledger.rows.flatMap(r => r.events);
    const monthStart = today.slice(0, 7) + "-01", monthEnd = addMonths(monthStart, 1), yearEnd = addMonths(today, 12);
    const inRange = (e, a, b) => e.amount != null && e.date >= a && e.date < b;
    const thisMonth = all.filter(e => inRange(e, monthStart, monthEnd)).sort((a, b) => a.date.localeCompare(b.date));
    const next12 = all.filter(e => inRange(e, today, yearEnd));
    const sum = xs => Math.round(xs.reduce((a, e) => a + e.amount, 0) * 100) / 100;
    s.ledger.totals.this_month = { total: sum(thisMonth), items: thisMonth };
    s.ledger.totals.next_12 = { total: sum(next12), count: next12.length };
    const keep = new Set(s.ledger.rows.map(r => r.instrument));
    s.ledger.totals.by_counterparty = s.ledger.totals.by_counterparty.map(c => {
      const items = c.items.filter(i => keep.has(i.instrument));
      return { ...c, items, total: items.reduce((a, i) => a + i.amount, 0) };
    }).filter(c => c.items.length).sort((a, b) => b.total - a.total);
    s.outbox.forEach(d => {
      const st = local.outbox[d.id] || {};
      d.status = st.status || "Draft"; d.body = st.body || d.body; d.approved_at = st.approved_at || null;
    });
    const seller = s.deal.seller;
    const sellerRows = s.ledger.rows.filter(r => r.counterparty.startsWith(seller));
    s.seller_view.rows = sellerRows;
    s.seller_view.upcoming = sellerRows.flatMap(r => r.events).filter(e => e.date >= today && e.amount).sort((a, b) => a.date.localeCompare(b.date)).slice(0, 12);
    s.seller_view.outstanding = s.ledger.totals.by_counterparty.find(c => c.counterparty === seller) || null;
    s.extraction_source = "cache";
    return s;
  }

  window.StaticApi = async function (path, body) {
    if (path === "/api/state") return compute();
    let m;
    if ((m = path.match(/^\/api\/review\/(.+)$/))) {
      const e = local.review[m[1]] = local.review[m[1]] || {};
      if (body.decision !== undefined) { if (body.decision) e.decision = body.decision; else delete e.decision; }
      if (body.edits) e.edits = { ...(e.edits || {}), ...body.edits };
      persist(); return { ok: true, review: e };
    }
    if ((m = path.match(/^\/api\/outbox\/(.+)$/))) {
      const base = BASE.state.outbox.find(d => d.id === m[1]);
      const e = local.outbox[m[1]] = local.outbox[m[1]] || {};
      if (body.action === "approve") { e.status = base.approved_label; e.approved_at = BASE.state.today; }
      else if (body.action === "edit") { e.body = body.body; e.status = "Edited, awaiting approval"; }
      else if (body.action === "unapprove") { delete e.status; delete e.approved_at; }
      persist(); return { ok: true };
    }
    if (path === "/api/schedule-payment") return BASE.verdicts[body.obligation_id] || { allowed: false, headline: "Unknown obligation.", reason: "", citations: [] };
    if (path === "/api/month-end") return BASE.state.month_end;
    if (path === "/api/extract/live") return { started: false, reason: "Live extraction runs in the local build only. This hosted copy serves the cached extraction." };
    if (path === "/api/extract/status") return { running: false, lines: [], exit_code: 0 };
    if (path === "/api/reset") { local = { review: {}, outbox: {} }; persist(); return { ok: true }; }
    return {};
  };
})();
"""

# ---------------------------------------------------------------- html
index = (STATIC / "index.html").read_text()
body = re.search(r"<body>(.*)</body>", index, re.S).group(1)
body = body.replace('<script src="/static/app.js"></script>', "")
body = body.replace("Re-run Extraction", "Re-run Extraction")  # label unchanged; shim explains it is local only
data_json = json.dumps({"state": state, "verdicts": verdicts}, separators=(",", ":")).replace("</", "<\\/")
page = f"""<title>RolledCo Servicing Demo</title>
<meta name="description" content="RolledCo demo with synthetic data. Servicing layer for post-close money in a small business acquisition. RolledCo does not hold or move funds.">
<style>
{css}
</style>
{body}
<div id="prerender" hidden><pre>{html.escape(summary)}</pre></div>
<noscript><pre style="white-space:pre-wrap;padding:16px">{html.escape(summary)}</pre></noscript>
<script>window.__ROLLEDCO__ = {data_json};</script>
<script>{shim}</script>
<script>{js}</script>
"""

if DIST.exists():
    shutil.rmtree(DIST)
(DIST / "binder").mkdir(parents=True)
(DIST / "index.html").write_text(page)
for pdf in sorted((ROOT / "seed" / "binder").glob("*.pdf")):
    shutil.copy(pdf, DIST / "binder" / pdf.name)
print(f"wrote dist/index.html ({len(page.encode()) / 1024:.0f} KB) and {len(list((DIST / 'binder').iterdir()))} PDFs")
