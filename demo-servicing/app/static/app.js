/* RolledCo servicing demo. Vanilla JS, one page, no build step. */
(function () {
  "use strict";

  const S = { data: null, screen: "binder", sellerView: false, extracted: false, verdicts: {}, monthEnd: null, editing: {} };
  const $ = (sel, el = document) => el.querySelector(sel);
  const content = $("#content");

  // ------------------------------------------------------------ helpers
  const money = (n, cents = true) => n == null ? "" :
    "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: cents ? 2 : 0 });
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function parseD(s) { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); }
  function longDate(s) { if (!s) return ""; const d = parseD(s); return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`; }
  function shortDate(s) { if (!s) return ""; const d = parseD(s); return `${MON[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`; }
  function esc(s) { return String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  function h(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }
  const FLAG_SVG = `<svg viewBox="0 0 16 16" fill="currentColor"><path d="M3 1.5v13h1.5V9.5h7.2l-1.4-3 1.4-3H4.5V1.5z"/></svg>`;

  async function api(path, body) {
    const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
    return r.json();
  }
  async function load() { S.data = await api("/api/state"); updateChrome(); }
  function toast(msg) {
    let t = $(".toast"); if (!t) { t = h(`<div class="toast"></div>`); document.body.appendChild(t); }
    t.textContent = msg; t.style.display = "block"; clearTimeout(t._t); t._t = setTimeout(() => t.style.display = "none", 2200);
  }

  // ------------------------------------------------------------ chrome
  const TITLES = {
    binder: ["Closing Binder", d => `${d.documents.length} documents for the acquisition of ${d.deal.seller_entity}, closed ${longDate(d.deal.close_date)}`],
    review: ["Review", d => `Extracted obligations awaiting a person's decision`],
    ledger: ["Ledger", d => `Every payment the buyer owes after close, ten years from ${longDate(d.deal.close_date)}`],
    monitor: ["Monitor", d => `Compliance, month-end calculation and lender reporting`],
    outbox: ["Outbox", d => `Drafts prepared by the servicing agent. Nothing is sent from here`],
  };
  function updateChrome() {
    const d = S.data;
    $("#nav-deal-name").textContent = d.deal.name;
    $("#nav-deal-buyer").textContent = d.deal.buyer;
    $("#clock").textContent = `As of ${longDate(d.today)}`;
    $("#model-chip").textContent = `${d.extraction_source === "live" ? "Live extraction" : "Cached extraction"}, ${d.model}`;
    const flags = d.obligations.filter(o => o.conflicts && o.conflicts.length && o.review.decision !== "reject").length;
    $("#badge-review").textContent = flags ? String(flags) : "";
    const pending = d.outbox.filter(x => x.status === "Draft").length;
    $("#badge-outbox").textContent = pending ? String(pending) : "";
    document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.screen === S.screen));
    $("#nav").classList.toggle("disabled", S.sellerView);
    if (S.sellerView) {
      $("#screen-title").textContent = "Seller View";
      $("#screen-sub").textContent = `Read only. What ${d.deal.seller} is owed and when`;
    } else {
      $("#screen-title").textContent = TITLES[S.screen][0];
      $("#screen-sub").textContent = TITLES[S.screen][1](d);
    }
  }
  function render() {
    updateChrome();
    content.scrollTop = 0;
    if (S.sellerView) return renderSeller();
    ({ binder: renderBinder, review: renderReview, ledger: renderLedger, monitor: renderMonitor, outbox: renderOutbox })[S.screen]();
  }
  function go(screen) { S.screen = screen; render(); }

  document.querySelectorAll(".nav-item").forEach(b => b.addEventListener("click", () => go(b.dataset.screen)));
  $("#seller-toggle").addEventListener("change", e => { S.sellerView = e.target.checked; render(); });
  $("#reset-btn").addEventListener("click", async () => {
    await api("/api/reset", {}); S.extracted = false; S.verdicts = {}; S.monthEnd = null; await load(); go("binder"); toast("Demo reset");
  });

  // ------------------------------------------------------------ drawer
  const drawer = $("#drawer"), backdrop = $("#drawer-backdrop");
  function openDrawer(html) { drawer.innerHTML = `<button class="drawer-close" aria-label="Close">&times;</button>` + html; drawer.classList.add("open"); backdrop.classList.add("open"); $(".drawer-close").onclick = closeDrawer; }
  function closeDrawer() { drawer.classList.remove("open"); backdrop.classList.remove("open"); }
  backdrop.addEventListener("click", closeDrawer);

  function citeHtml(c) {
    const doc = c.document || c.with_document;
    return `<blockquote class="quote">${esc(c.quote)}</blockquote>
      <div class="cite">${esc(c.section)} &middot; <a href="/binder/${esc(doc)}#page=${c.page}" target="_blank" rel="noopener">${esc(doc)}</a>, page ${c.page}</div>`;
  }

  // ------------------------------------------------------------ 1 binder
  function renderBinder() {
    const d = S.data;
    const rows = d.documents.map((doc, i) => `
      <tr class="doc-row"><td>${String(i + 1).padStart(2, "0")}</td>
        <td><div class="doc-title">${esc(doc.title)}</div><div class="doc-file">${esc(doc.file)}</div></td>
        <td>${esc(doc.kind)}</td><td class="num">${doc.dated ? shortDate(doc.dated) : ""}</td><td class="num">${doc.pages}</td>
        <td><a href="/binder/${esc(doc.file)}" target="_blank" rel="noopener">Open</a></td></tr>`).join("");
    content.innerHTML = `
      <div class="binder-layout">
        <div>
          <div class="sec-head"><h2>Uploaded Documents</h2><span class="muted">Synthetic closing binder, ${d.documents.reduce((a, x) => a + x.pages, 0)} pages</span></div>
          <div class="card"><table class="grid"><thead><tr><th></th><th>Document</th><th>Kind</th><th class="num">Dated</th><th class="num">Pages</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
        </div>
        <div>
          <div class="sec-head"><h2>Extraction</h2></div>
          <div class="panel" id="extract-panel">
            <p class="muted small" style="margin:0 0 12px">Four agents read the binder in sequence. Results are cached, so this replay is instant. Re-run calls the Anthropic API with the model in ANTHROPIC_MODEL.</p>
            <div class="row" style="margin-bottom:6px">
              <button class="btn btn-primary" id="extract-btn">Extract Obligations</button>
              <button class="btn btn-ghost" id="rerun-btn" title="Calls the Anthropic API">Re-run Extraction</button>
            </div>
            <ul class="agents" id="agents"></ul>
            <div id="extract-summary"></div>
          </div>
        </div>
      </div>`;
    $("#extract-btn").onclick = () => runCachedExtraction();
    $("#rerun-btn").onclick = () => runLiveExtraction();
    if (S.extracted) { renderAgents(AGENTS.map(a => ({ ...a, state: "done", lines: a.cachedLines(d) }))); showExtractSummary(); }
  }

  const AGENTS = [
    { name: "Reader", role: "Reads each document and pulls out every obligation", cachedLines: d => d.documents.map(x => `Reading ${x.file} (${x.pages} pages)`).concat([`${d.obligations.length} obligations found across ${d.documents.length} documents`]) },
    { name: "Compliance", role: "Cross-checks documents, flags conflicts and missing terms", cachedLines: d => [`Cross-checking ${d.obligations.length} obligations across ${d.documents.length} documents`].concat(d.obligations.flatMap(o => (o.conflicts || []).map(c => `Flag: ${o.instrument}. ${c.title}`))) },
    { name: "Calculation", role: "Computes amounts, dates and accruals from the terms", cachedLines: d => {
        const l = d.ledger; const sba = l.rows.find(r => r.type === "sba_loan");
        return [`Computing next dates and accrued interest as of ${shortDate(d.today)}`,
          sba ? `${sba.instrument}: ${money(sba.events[0].amount)} monthly, ${sba.events.filter(e => e.date >= d.today).length} payments remaining` : "",
          `Seller Note A: interest accruing, no payment while the SBA loan is outstanding`,
          `Seller Note B: revenue test tracking ${money(d.month_end.annualized, false)} against ${money(d.month_end.threshold, false)}`].filter(Boolean);
      } },
    { name: "Servicing", role: "Builds the ledger and drafts instructions for approval", cachedLines: d => [`Ledger built: ${d.ledger.rows.reduce((a, r) => a + r.events.length, 0)} dated events over 10 years`, `${d.outbox.length} drafts queued in the Outbox for a person to approve`] },
  ];

  function renderAgents(agents) {
    $("#agents").innerHTML = agents.map(a => {
      let lines = a.lines || [];
      if (a.state === "done" && a.name === "Reader" && lines.length > 3) {
        const reads = lines.filter(l => l.startsWith("Reading "));
        const pages = reads.reduce((n, l) => n + (parseInt((l.match(/\((\d+) page/) || [])[1]) || 0), 0);
        lines = [`Read ${reads.length} documents, ${pages} pages`].concat(lines.filter(l => !l.startsWith("Reading ")));
      }
      return `
      <li class="agent ${a.state || ""}"><div class="agent-dot"></div>
        <div><div class="agent-name">${a.name}</div><div class="agent-role">${a.role}</div>
          <ul class="agent-log">${lines.map(l => `<li class="${l.startsWith("Flag:") ? "flagline" : ""}">${esc(l)}</li>`).join("")}</ul></div></li>`; }).join("");
  }
  function showExtractSummary() {
    const d = S.data; const flags = d.obligations.reduce((a, o) => a + (o.conflicts || []).length, 0);
    $("#extract-summary").innerHTML = `<div class="extract-summary row-between">
      <div><div class="big">${d.obligations.length} obligations, ${flags} flags</div><div class="muted small">Model ${esc(d.model)} &middot; ${d.extraction_source === "live" ? "live run" : "cached result"}</div></div>
      <button class="btn btn-primary" id="to-review">Open Review</button></div>`;
    $("#to-review").onclick = () => go("review");
  }
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  async function runCachedExtraction() {
    const d = S.data; $("#extract-btn").disabled = true; $("#extract-summary").innerHTML = "";
    const agents = AGENTS.map(a => ({ ...a, state: "", lines: [] }));
    renderAgents(agents);
    for (const a of agents) {
      a.state = "running"; renderAgents(agents);
      const lines = a.cachedLines(d);
      for (const l of lines) { await sleep(a.name === "Reader" ? 210 : 420); a.lines.push(l); renderAgents(agents); }
      await sleep(250); a.state = "done"; renderAgents(agents);
    }
    S.extracted = true; $("#extract-btn").disabled = false; showExtractSummary();
  }
  async function runLiveExtraction() {
    const r = await api("/api/extract/live", {});
    if (!r.started) { toast(r.reason); return; }
    $("#extract-btn").disabled = true; $("#rerun-btn").disabled = true; $("#extract-summary").innerHTML = "";
    const agents = AGENTS.map(a => ({ ...a, state: "", lines: [] }));
    renderAgents(agents);
    while (true) {
      const st = await api("/api/extract/status");
      agents.forEach(a => a.lines = []);
      let current = null;
      for (const line of st.lines) {
        const m = line.match(/^STEP (\w+): (.*)$/);
        if (m) { const a = agents.find(x => x.name === m[1]); if (a) { current = a; a.lines.push(m[2]); } }
        else if (current) current.lines.push(line);
      }
      agents.forEach((a, i) => { a.state = a.lines.length ? (st.running && a === current ? "running" : "done") : ""; });
      renderAgents(agents);
      if (!st.running) {
        if (st.exit_code === 0) { await load(); S.extracted = true; render(); showExtractSummary(); toast("Live extraction complete"); }
        else { toast("Extraction failed. See the log."); $("#extract-btn").disabled = false; $("#rerun-btn").disabled = false; }
        break;
      }
      await sleep(900);
    }
  }

  // ------------------------------------------------------------ 2 review
  function renderReview() {
    const d = S.data;
    const obs = d.obligations;
    const flags = obs.filter(o => o.conflicts && o.conflicts.length).length;
    const approved = obs.filter(o => o.review.decision === "approve").length;
    const rejected = obs.filter(o => o.review.decision === "reject").length;
    const rows = obs.map(o => {
      const flagged = o.conflicts && o.conflicts.length;
      const conf = Math.round(o.confidence * 100);
      const dec = o.review.decision;
      const status = dec === "approve" ? `<span class="chip chip-ink">Approved</span>` : dec === "reject" ? `<span class="chip">Rejected</span>` : dec === "edit" ? `<span class="chip chip-outline">Edited</span>` : "";
      return `<tr class="${flagged ? "flagged" : ""} ${dec === "reject" ? "rejected" : ""}" data-id="${o.id}">
        <td><div class="inst-name">${esc(o.instrument)}</div><div class="inst-type">${esc(o.type.replace("_", " "))}</div>
          ${flagged ? o.conflicts.map(c => `<div class="flag" style="margin-top:6px">${FLAG_SVG}${c.kind === "conflict" ? "Conflict" : "Missing term"}</div><div class="flag-reason">${esc(c.title)}. ${esc(c.description.split(". ").slice(0, 2).join(". "))}.</div>`).join("") : ""}
        </td>
        <td>${esc(o.counterparty)}</td>
        <td class="num"><div>${o.amount != null ? money(o.amount, false) : "<span class='muted'>Non-monetary</span>"}</div><div class="muted amt-text">${esc(o.amount_text)}</div></td>
        <td class="num">${o.next_date ? shortDate(o.next_date) : "<span class='muted'>Contingent</span>"}</td>
        <td><div class="conf"><div class="conf-bar"><div class="conf-fill ${conf < 80 ? "low" : ""}" style="width:${conf}%"></div></div><span class="conf-num">${conf}%</span></div></td>
        <td><a href="#" class="view-src" data-id="${o.id}">View Source</a></td>
        <td><div class="review-actions">${status || `<button class="btn" data-act="approve">Approve</button><button class="btn" data-act="edit">Edit</button><button class="btn" data-act="reject">Reject</button>`}${status ? `<button class="btn btn-ghost" data-act="undo">Undo</button>` : ""}</div></td>
      </tr>`;
    }).join("");
    content.innerHTML = `
      <div class="summary-chips">
        <span class="chip">${obs.length} obligations</span>
        <span class="chip ${flags ? "chip-crimson" : ""}">${flags} flagged</span>
        <span class="chip">${approved} approved</span>
        ${rejected ? `<span class="chip">${rejected} rejected</span>` : ""}
        <span class="chip chip-quiet">Confidence below 80% is shown in crimson</span>
      </div>
      <div class="card"><table class="grid review-table">
        <thead><tr><th style="width:30%">Instrument</th><th>Counterparty</th><th class="num">Amount</th><th class="num">Next Date</th><th>Confidence</th><th>Source</th><th>Decision</th></tr></thead>
        <tbody>${rows}</tbody></table></div>`;
    content.querySelectorAll(".view-src").forEach(a => a.onclick = e => { e.preventDefault(); showSource(a.dataset.id); });
    content.querySelectorAll("[data-act]").forEach(b => b.onclick = async () => {
      const id = b.closest("tr").dataset.id, act = b.dataset.act;
      if (act === "edit") return showEdit(id);
      await api(`/api/review/${id}`, { decision: act === "undo" ? "" : act });
      if (act === "undo") { await api(`/api/review/${id}`, { decision: null }); }
      await load(); render();
      if (act === "approve") toast("Approved. The ledger keeps this row.");
      if (act === "reject") toast("Rejected. Removed from the ledger.");
    });
  }
  function showSource(id) {
    const o = S.data.obligations.find(x => x.id === id);
    const doc = S.data.documents.find(x => x.file === o.source.document);
    openDrawer(`
      <h2>${esc(o.instrument)}</h2>
      <div class="muted small">${esc(doc ? doc.title : o.source.document)}</div>
      <div class="field"><label>Quoted Clause</label>${citeHtml(o.source)}</div>
      <div class="field"><label>Amount or Formula</label><div>${esc(o.formula)}</div></div>
      ${o.compliance_rules && o.compliance_rules.length ? `<div class="field"><label>Compliance Rules</label><ul style="margin:0;padding-left:18px">${o.compliance_rules.map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>` : ""}
      ${o.conditions && o.conditions.length ? `<div class="field"><label>Conditions</label><ul style="margin:0;padding-left:18px">${o.conditions.map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>` : ""}
      ${(o.conflicts || []).map(c => `<div class="field"><label><span class="flag">${FLAG_SVG}${c.kind === "conflict" ? "Conflict" : "Missing term"}</span></label>
          <div style="margin:6px 0 8px">${esc(c.description)}</div>${citeHtml(c)}</div>`).join("")}
      <div class="field"><label>Confidence</label>${Math.round(o.confidence * 100)}%${o.notes ? ` &middot; ${esc(o.notes)}` : ""}</div>`);
  }
  function showEdit(id) {
    const o = S.data.obligations.find(x => x.id === id);
    openDrawer(`
      <h2>Edit ${esc(o.instrument)}</h2>
      <div class="muted small">Changes apply to the ledger and drafts. The source document is not changed.</div>
      <div class="field"><label>Counterparty</label><input id="e-cp" value="${esc(o.counterparty)}"></div>
      <div class="field"><label>Amount</label><input id="e-amt" type="number" step="0.01" value="${o.amount ?? ""}"></div>
      <div class="field"><label>Amount per payment</label><input id="e-each" type="number" step="0.01" value="${o.schedule.amount_each ?? ""}"></div>
      <div class="field"><label>First or next payment date</label><input id="e-date" type="date" value="${o.schedule.first_date ?? ""}"></div>
      <div class="row" style="margin-top:18px"><button class="btn btn-primary" id="e-save">Save</button><button class="btn" id="e-cancel">Cancel</button></div>`);
    $("#e-cancel").onclick = closeDrawer;
    $("#e-save").onclick = async () => {
      const edits = { counterparty: $("#e-cp").value };
      if ($("#e-amt").value !== "") edits.amount = Number($("#e-amt").value);
      if ($("#e-each").value !== "") edits.amount_each = Number($("#e-each").value);
      if ($("#e-date").value) edits.first_date = $("#e-date").value;
      await api(`/api/review/${id}`, { decision: "edit", edits });
      closeDrawer(); await load(); render(); toast("Saved");
    };
  }

  // ------------------------------------------------------------ 3 ledger
  function renderLedger() {
    const d = S.data, L = d.ledger, T = L.totals;
    const thisMonth = T.this_month.items.map(e => `<li><span>${esc(e.instrument)}, ${shortDate(e.date)}</span><span class="num">${money(e.amount)}</span></li>`).join("");
    const byCp = T.by_counterparty.map(c => `<li><span>${esc(c.counterparty)}</span><span class="num">${money(c.total, false)}</span></li>`).join("");
    content.innerHTML = `
      <div class="stats">
        <div class="stat"><div class="stat-label">Due This Month, ${MONTHS[parseD(d.today).getMonth()]} ${parseD(d.today).getFullYear()}</div><div class="stat-value">${money(T.this_month.total)}</div><ul class="stat-list">${thisMonth}</ul></div>
        <div class="stat"><div class="stat-label">Due Next 12 Months</div><div class="stat-value">${money(T.next_12.total)}</div><ul class="stat-list"><li><span>${T.next_12.count} scheduled payments</span><span class="num">${shortDate(d.today)} onward</span></li><li class="muted"><span>Seller notes stay on standby through this period</span></li></ul></div>
        <div class="stat"><div class="stat-label">Total Outstanding by Counterparty</div><div class="stat-value">${money(T.by_counterparty.reduce((a, c) => a + c.total, 0), false)}</div><ul class="stat-list" style="columns:2;column-gap:18px">${byCp}</ul></div>
      </div>
      <div class="timeline-wrap">
        <div class="timeline-head"><h2>Ten Year Timeline</h2>
          <div class="legend"><span><i class="lg-pay"></i>Payment</span><span><i class="lg-pay lg-adj"></i>Payment, amount subject to adjustment</span><span><i class="lg-del"></i>Deliverable</span><span><i class="lg-standby"></i>Standby, no payments</span><span><i class="lg-today"></i>Today</span><span class="flag">${FLAG_SVG}Flagged in Review</span></div></div>
        <div id="timeline"></div>
      </div>
      <div class="tip" id="tip"></div>`;
    drawTimeline(L);
  }

  function drawTimeline(L) {
    const rows = L.rows;
    const W = Math.max(content.clientWidth - 2, 900), LABEL = 290, PAD_R = 18, TOP = 34, RH = 36, BOT = 8;
    const H = TOP + rows.length * RH + BOT;
    const t0 = parseD(L.horizon[0]), t1 = parseD(L.horizon[1]);
    const span = t1 - t0, x = dt => LABEL + (parseD(dt) - t0) / span * (W - LABEL - PAD_R);
    let svg = `<svg class="timeline" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">`;
    // year grid
    svg += `<text class="year" x="${LABEL + 5}" y="${TOP - 14}">${t0.getFullYear()}</text>`;
    for (let y = t0.getFullYear(); y <= t1.getFullYear(); y++) {
      const d = new Date(y, 0, 1); if (d < t0 || d > t1) continue;
      const xx = LABEL + (d - t0) / span * (W - LABEL - PAD_R);
      svg += `<line class="yearline" x1="${xx}" x2="${xx}" y1="${TOP - 10}" y2="${H - BOT}"/><text class="year" x="${xx + 5}" y="${TOP - 14}">${y}</text>`;
    }
    rows.forEach((r, i) => {
      const y = TOP + i * RH, cy = y + RH / 2;
      svg += `<line class="rowline" x1="${LABEL}" x2="${W - PAD_R}" y1="${y + RH}" y2="${y + RH}"/>`;
      const name = r.instrument;
      svg += `<text class="ylabel" x="14" y="${cy - 2}">${esc(name)}</text><text class="ysub" x="14" y="${cy + 12}">${esc(r.counterparty.split(",")[0])}</text>`;
      if (r.flagged) svg += `<g transform="translate(${LABEL - 22}, ${cy - 7})" fill="#8B1A1A"><path d="M3 1.5v13h1.5V9.5h7.2l-1.4-3 1.4-3H4.5V1.5z"/></g>`;
      if (r.standby) {
        const a = x(r.standby[0]), b = x(r.standby[1]);
        svg += `<rect class="standby" x="${a}" y="${y + 5}" width="${b - a}" height="${RH - 10}" rx="2"/><text class="ysub" x="${a + 6}" y="${cy + 4}">Standby${r.type === "seller_note" && r.events.length === 1 ? ", interest accruing, no payments" : ", no payments"}</text>`;
      }
      r.events.forEach((e, j) => {
        const ex = x(e.date);
        if (e.kind === "deliverable") svg += `<circle class="del" cx="${ex}" cy="${cy}" r="3.4"/>`;
        else if (r.type === "seller_note" && r.events.length > 1) svg += `<circle class="pay contract" cx="${ex}" cy="${cy}" r="3.2"/>`;
        else svg += `<circle class="pay" cx="${ex}" cy="${cy}" r="${r.events.length > 60 ? 2.4 : 3.6}"/>`;
        svg += `<rect class="hit" x="${ex - 3.5}" y="${y + 3}" width="7" height="${RH - 6}" data-row="${i}" data-ev="${j}"/>`;
      });
    });
    const tx = x(L.today);
    svg += `<line class="today" x1="${tx}" x2="${tx}" y1="${TOP - 10}" y2="${H - BOT}"/><text class="todaylabel" x="${tx + 5}" y="${H - BOT - 4}">Today, ${shortDate(L.today)}</text>`;
    svg += `</svg>`;
    $("#timeline").innerHTML = svg;
    const tip = $("#tip");
    $("#timeline").addEventListener("mousemove", ev => {
      const t = ev.target.closest(".hit");
      if (!t) { tip.style.display = "none"; return; }
      const r = rows[+t.dataset.row], e = r.events[+t.dataset.ev];
      tip.innerHTML = `<b>${esc(r.instrument)}</b><br>${longDate(e.date)}<br>${e.amount != null ? money(e.amount) + ", " : ""}${esc(e.label)}`;
      tip.style.display = "block"; tip.style.left = (ev.clientX + 14) + "px"; tip.style.top = (ev.clientY + 14) + "px";
    });
    $("#timeline").addEventListener("mouseleave", () => tip.style.display = "none");
    $("#timeline").addEventListener("click", ev => {
      const t = ev.target.closest(".hit"); if (!t) return;
      const r = rows[+t.dataset.row];
      openDrawer(`<h2>${esc(r.instrument)}</h2><div class="muted small">${esc(r.counterparty)} &middot; ${esc(r.amount_text || "")}</div>
        <div class="field"><label>Schedule, ${r.events.length} events</label>
        <table class="grid"><thead><tr><th>Date</th><th>Item</th><th class="num">Amount</th></tr></thead><tbody>
        ${r.events.map(e => `<tr><td class="num" style="text-align:left">${shortDate(e.date)}</td><td>${esc(e.label)}</td><td class="num">${e.amount != null ? money(e.amount) : ""}</td></tr>`).join("")}
        </tbody></table></div>`);
    });
  }

  // ------------------------------------------------------------ 4 monitor
  function renderMonitor() {
    const d = S.data;
    const payable = d.obligations.filter(o => ["seller_note", "consulting", "retention_bonus", "holdback"].includes(o.type));
    const checks = payable.map(o => `<li class="check-item" data-id="${o.id}">
        <div><div class="inst-name">${esc(o.instrument)}</div><div class="small muted">${esc(o.counterparty)} &middot; next ${o.next_date ? shortDate(o.next_date) : "n/a"}${o.schedule.standby_end ? ` &middot; standby to ${shortDate(o.schedule.standby_end)}` : ""}</div></div>
        <button class="btn btn-sm" data-sched="${o.id}">Schedule Payment</button></li>`).join("");
    const rep = d.reporting.map(r => `<tr><td><div class="inst-name">${esc(r.period)}</div><div class="small muted">${esc(r.instrument.replace("Lender Reporting, ", ""))}</div></td>
        <td class="num">${shortDate(r.due)}</td><td class="num">${r.days < 0 ? "" : r.days + " days"}</td>
        <td><span class="status-pill ${r.status === "Submitted" ? "sub" : r.status === "In Progress" ? "warn" : "ok"}">${r.status}</span></td><td class="small muted">${esc(r.detail)}</td></tr>`).join("");
    content.innerHTML = `
      <div class="monitor-grid">
        <div class="card" style="padding:18px 20px">
          <div class="sec-head"><h2>Compliance Check</h2><span class="muted">Every payment is checked against the standby terms before it is scheduled</span></div>
          <div id="verdict"></div>
          <ul class="check-list">${checks}</ul>
        </div>
        <div class="card" style="padding:18px 20px">
          <div class="sec-head"><h2>Month-End Run</h2><span class="muted">Reads the monthly P&amp;L files in seed/pnl</span></div>
          <div class="row-between" style="margin-bottom:10px">
            <div class="small muted">Seller Note B revenue test. Measurement date ${longDate(d.month_end.measurement_date)}, ${d.month_end.months_remaining} months away.</div>
            <button class="btn btn-primary btn-sm" id="run-me">Run Month End</button>
          </div>
          <div id="month-end"></div>
        </div>
        <div class="card span2" style="padding:18px 20px">
          <div class="sec-head"><h2>Lender Reporting</h2><span class="muted">${esc(d.deal.lender)} covenants, next twelve months</span></div>
          <table class="grid"><thead><tr><th>Period</th><th class="num">Due</th><th class="num">In</th><th>Status</th><th>Detail</th></tr></thead><tbody>${rep}</tbody></table>
        </div>
      </div>`;
    content.querySelectorAll("[data-sched]").forEach(b => b.onclick = async () => {
      const id = b.dataset.sched;
      const v = await api("/api/schedule-payment", { obligation_id: id });
      S.verdicts[id] = v; showVerdict(v, id);
      if (v.allowed) toast("Draft payment instruction is in the Outbox");
    });
    $("#run-me").onclick = async () => { S.monthEnd = await api("/api/month-end", {}); showMonthEnd(); };
    if (S.monthEnd) showMonthEnd();
    const last = Object.keys(S.verdicts).pop(); if (last) showVerdict(S.verdicts[last], last);
  }
  function showVerdict(v, id) {
    $("#verdict").innerHTML = `<div class="verdict ${v.allowed ? "" : "blocked"}">
      <h3>${esc(v.headline || (v.allowed ? "Allowed" : "Blocked"))}</h3>
      <div>${esc(v.reason)}</div>
      ${v.citations && v.citations.length ? `<div class="cites">${v.citations.map(citeHtml).join("")}</div>` : ""}
      ${v.allowed ? `<div style="margin-top:12px"><button class="btn btn-sm" id="to-outbox">Open Outbox</button></div>` : ""}
    </div>`;
    const b = $("#to-outbox"); if (b) b.onclick = () => go("outbox");
  }
  function showMonthEnd() {
    const m = S.monthEnd, max = Math.max(...m.months.map(x => x.revenue));
    const perMonthThreshold = m.threshold / 12;
    const bars = m.months.map(x => `<div class="revbar"><div class="val">${money(x.revenue / 1000, false)}k</div><div class="bar ${x.revenue < perMonthThreshold ? "under" : ""}" style="height:${Math.round(x.revenue / max * 62)}px"></div><div>${MON[+x.month.split("-")[1] - 1]}</div></div>`).join("");
    $("#month-end").innerHTML = `
      <div class="row-between"><span class="small muted">Monthly revenue, ${m.months[0].file} to ${m.months[m.months.length - 1].file}</span><span class="status-pill ${m.shortfall > 0 ? "warn" : "ok"}">${esc(m.status)}</span></div>
      <div class="revbars">${bars}</div>
      <div class="thresh-line">Threshold pace ${money(perMonthThreshold, false)} per month. Crimson bars are below pace.</div>
      <table class="math"><tbody>${m.steps.map(s => `<tr class="${s.emphasis ? "emph" : ""}"><td>${esc(s.label)}</td><td class="num">${money(s.value)}</td></tr>`).join("")}</tbody></table>
      <div class="small muted" style="margin-top:8px">Projection only. The test is measured once, on ${longDate(m.measurement_date)}, on actual trailing twelve month revenue. Nothing changes on the note until then.</div>`;
  }

  // ------------------------------------------------------------ 5 outbox
  function renderOutbox() {
    const d = S.data;
    content.innerHTML = `<div class="drafts">${d.outbox.map(x => {
      const approved = x.status !== "Draft" && x.status !== "Edited, awaiting approval";
      const editing = S.editing[x.id];
      return `<div class="draft ${approved ? "approved" : ""}" data-id="${x.id}">
        <div class="draft-head"><div><div class="draft-kind">${esc(x.kind)}</div><div class="draft-title">${esc(x.title)}</div><div class="draft-to">To: ${esc(x.to)}</div></div>
          <span class="chip ${approved ? "chip-crimson" : x.status === "Draft" ? "" : "chip-outline"}">${esc(x.status)}</span></div>
        <div class="draft-body">${editing ? `<textarea id="ta-${x.id}">${esc(x.body)}</textarea>` : `<pre>${esc(x.body)}</pre>`}</div>
        <div class="draft-foot">
          ${editing ? `<button class="btn btn-primary" data-act="save">Save</button><button class="btn" data-act="cancel">Cancel</button>`
            : approved ? `<button class="btn btn-ghost" data-act="unapprove">Undo Approval</button><span class="muted small">Approved ${longDate(x.approved_at)}. Nothing has been sent. The buyer's bank or the buyer acts on this.</span>`
            : `<button class="btn btn-primary" data-act="approve">Approve</button><button class="btn" data-act="edit">Edit</button><span class="muted small">Approving records the decision. RolledCo does not send or pay.</span>`}
        </div></div>`;
    }).join("")}</div>`;
    content.querySelectorAll("[data-act]").forEach(b => b.onclick = async () => {
      const id = b.closest(".draft").dataset.id, act = b.dataset.act;
      if (act === "edit") { S.editing[id] = true; return renderOutbox(); }
      if (act === "cancel") { delete S.editing[id]; return renderOutbox(); }
      if (act === "save") { await api(`/api/outbox/${id}`, { action: "edit", body: $(`#ta-${id}`).value }); delete S.editing[id]; }
      else await api(`/api/outbox/${id}`, { action: act });
      await load(); renderOutbox();
      if (act === "approve") toast("Approved. Ready for the buyer. Nothing was sent.");
    });
  }

  // ------------------------------------------------------------ seller view
  function renderSeller() {
    const d = S.data, v = d.seller_view;
    const row = id => v.rows.find(r => r.id === id);
    const noteA = row("note-a"), noteB = row("note-b"), cons = row("consulting"), hb = row("holdback");
    const obs = id => d.obligations.find(o => o.id === id);
    const outstanding = v.outstanding ? v.outstanding.items : [];
    const item = inst => outstanding.find(i => i.instrument === inst);
    const cards = [];
    if (noteA) cards.push(`<div class="seller-card"><h3>Seller Note A</h3><dl class="kv">
      <dt>Principal</dt><dd>${money(obs("note-a").amount, false)}</dd>
      <dt>Interest</dt><dd>${(obs("note-a").rate * 100).toFixed(0)}% simple, accruing. Balance with interest today ${money(item("Seller Note A").amount)}</dd>
      <dt>Payments</dt><dd>None while the SBA loan is outstanding. Full standby.</dd>
      <dt>Expected payoff</dt><dd>${longDate(noteA.events[0].date)}, ${money(noteA.events[0].amount)} including accrued interest</dd></dl></div>`);
    if (noteB) cards.push(`<div class="seller-card"><h3>Seller Note B</h3><dl class="kv">
      <dt>Principal</dt><dd>${money(obs("note-b").amount, false)}, subject to the revenue test at month 24</dd>
      <dt>Standby ends</dt><dd>${longDate(obs("note-b").schedule.standby_end)}</dd>
      <dt>First installment</dt><dd>${longDate(noteB.events[0].date)} per the note. The purchase agreement states a different month. Date to be confirmed with you before the standby period ends.</dd>
      <dt>Installments</dt><dd>${noteB.events.length} monthly, estimated ${money(noteB.events[0].amount)} each before any adjustment</dd></dl></div>`);
    if (cons) {
      const paid = cons.events.filter(e => e.date < d.today), next = cons.events.find(e => e.date >= d.today);
      cards.push(`<div class="seller-card"><h3>Consulting Agreement</h3><dl class="kv">
      <dt>Paid to date</dt><dd>${money(paid.reduce((a, e) => a + e.amount, 0))}, ${paid.length} monthly fees</dd>
      <dt>Next payment</dt><dd>${next ? `${money(next.amount)} on ${longDate(next.date)}` : "None"}</dd>
      <dt>Remaining</dt><dd>${cons.events.filter(e => e.date >= d.today).length} payments through ${longDate(cons.events[cons.events.length - 1].date)}</dd></dl></div>`);
    }
    if (hb) cards.push(`<div class="seller-card"><h3>Holdback</h3><dl class="kv">
      <dt>Held</dt><dd>${money(obs("holdback").amount, false)} by Ashcroft Lowe LLP, holdback agent</dd>
      <dt>Working capital</dt><dd>${d.servicing.nwc_settled ? `True-up settled ${longDate(d.servicing.nwc_settled_on)}, adjustment ${money(d.servicing.nwc_adjustment)}` : "True-up not yet settled"}</dd>
      <dt>Release</dt><dd>Due ${longDate(hb.events[0].date)}. Release instruction awaiting the buyer's approval.</dd></dl></div>`);
    content.innerHTML = `<div class="seller-wrap">
      <div class="row-between"><div><h2 style="font-size:26px">What ${esc(v.seller)} Is Owed</h2><div class="muted small">Prepared by ${esc(v.buyer)} as of ${longDate(v.today)}. Figures come from the signed closing documents.</div></div>
        <div class="stat" style="min-height:0;padding:10px 16px"><div class="stat-label">Outstanding to you</div><div class="stat-value" style="font-size:28px;margin:2px 0 0">${money(v.outstanding ? v.outstanding.total : 0, false)}</div></div></div>
      <div class="seller-cards">${cards.join("")}</div>
      <div class="sec-head"><h2>Upcoming Payments to You</h2><span class="muted">Next ${v.upcoming.length} scheduled items</span></div>
      <div class="card"><table class="grid"><thead><tr><th>Date</th><th>Instrument</th><th>Item</th><th class="num">Amount</th></tr></thead><tbody>
        ${v.upcoming.map(e => `<tr><td class="num" style="text-align:left">${shortDate(e.date)}</td><td>${esc(e.instrument)}</td><td>${esc(e.label)}</td><td class="num">${money(e.amount)}</td></tr>`).join("")}
      </tbody></table></div>
      <div class="readonly-note">This view is read only. Seller Note B amounts after the standby period depend on the revenue test and the date the parties confirm. RolledCo does not hold or move funds; payments come from the buyer's bank.</div>
    </div>`;
  }

  // ------------------------------------------------------------ boot
  load().then(render).catch(e => { content.innerHTML = `<div class="empty">${esc(e.message)}</div>`; });
})();
