"""
RolledCo servicing demo server. FastAPI plus one static page. No database.

    python app/server.py          -> http://localhost:8000

Reads data/obligations.json (cached extraction, or the output of extract.py).
Review decisions and outbox approvals live in data/state.json.
Nothing here sends anything or moves money. Approval is the end state.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from app import ledger  # noqa: E402

DATA = ROOT / "data"
OBLIGATIONS = DATA / "obligations.json"
CACHED = DATA / "obligations.cached.json"
# Vercel and other read-only hosts: STATE_DIR=/tmp keeps decisions for the life of the instance.
STATE = Path(os.environ.get("STATE_DIR", str(DATA))) / "state.json"
STATIC = ROOT / "app" / "static"
BINDER = ROOT / "seed" / "binder"
TODAY = date.fromisoformat(os.environ.get("DEMO_TODAY", "2027-01-15"))
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")

app = FastAPI(title="RolledCo Servicing Demo")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.mount("/binder", StaticFiles(directory=str(BINDER)), name="binder")

extract_job = {"running": False, "lines": [], "exit_code": None}


# ---------------------------------------------------------------- persistence
def load_data():
    path = OBLIGATIONS if OBLIGATIONS.exists() else CACHED
    if not path.exists():
        raise HTTPException(500, "No extraction found. Run extract.py or restore data/obligations.cached.json.")
    return json.loads(path.read_text())


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"review": {}, "outbox": {}, "servicing": default_servicing()}


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


def default_servicing():
    """Facts the servicing team records that the documents cannot know."""
    return {
        "nwc_settled": True,
        "nwc_settled_on": "2026-12-18",
        "nwc_adjustment": 0,
        "consulting_hours_this_month": 14,
        "q3_report_submitted_on": "2026-11-12",
        "sba_payments_made": 5,
        "consulting_payments_made": 5,
    }


def money(n):
    return f"${n:,.2f}"


def long_date(s):
    d = date.fromisoformat(s)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


# ---------------------------------------------------------------- outbox drafts
def build_drafts(data, state):
    obs = {o["id"]: o for o in data["obligations"]}
    deal = data["deal"]
    sv = state.get("servicing", default_servicing())
    led = ledger.build_ledger(data, TODAY, state)
    drafts = []

    consulting = obs.get("consulting")
    if consulting:
        nxt = next((e for e in ledger.build_events(ledger.apply_edits(consulting, state))
                    if date.fromisoformat(e["date"]) >= TODAY), None)
        if nxt:
            drafts.append({
                "id": "payment-consulting",
                "kind": "Payment Instruction",
                "title": f"Consulting Fee, {TODAY.strftime('%B %Y')}",
                "to": f"{deal['buyer']} operating account at {deal['lender']}",
                "approved_label": "Approved, ready for buyer's bank",
                "body": "\n".join([
                    f"PAYMENT INSTRUCTION  |  Prepared {long_date(TODAY.isoformat())}",
                    "",
                    f"Payer:        {deal['buyer']}",
                    f"From:         Operating account at {deal['lender']}, ending 4471",
                    f"Pay to:       {consulting['counterparty']}",
                    f"Amount:       {money(nxt['amount'])}",
                    f"Due:          {long_date(nxt['date'])}",
                    f"Method:       ACH, 2 business day settlement",
                    f"Memo:         Consulting Agreement dated {long_date(deal['close_date'])}, Section 4, fee for {TODAY.strftime('%B %Y')}",
                    "",
                    "Servicing checks",
                    f"  Standby:    Not applicable. The consulting fee is not subject to the Standby Creditor's Agreement.",
                    f"  Hours:      {sv['consulting_hours_this_month']} of 20 hours logged this month to date.",
                    f"  History:    {sv['consulting_payments_made']} of 12 payments made. This is payment {sv['consulting_payments_made'] + 1}.",
                    "",
                    "RolledCo prepares this instruction for a person to approve. The buyer's bank executes it. RolledCo does not hold or move funds.",
                ]),
            })

    seller = deal["seller"]
    note_a, note_b, holdback = obs.get("note-a"), obs.get("note-b"), obs.get("holdback")
    lines = [f"SELLER STATEMENT  |  {seller}  |  As of {long_date(TODAY.isoformat())}", "",
             f"Prepared by {deal['buyer']} for the acquisition of {deal['seller_entity']}, closed {long_date(deal['close_date'])}.", ""]
    if note_a:
        acc = ledger.simple_interest(note_a["amount"], note_a["rate"], date.fromisoformat(note_a["schedule"]["standby_start"]), TODAY)
        lines += ["Seller Note A",
                  f"  Principal:              {money(note_a['amount'])}",
                  f"  Interest accrued:       {money(acc)} at {note_a['rate']:.0%} simple since close",
                  f"  Payments made:          None. Full standby while the SBA loan is outstanding.",
                  f"  Expected maturity:      {long_date(note_a['next_date'])}", ""]
    if note_b:
        acc = ledger.simple_interest(note_b["amount"], note_b["rate"], date.fromisoformat(note_b["schedule"]["standby_start"]), TODAY)
        lines += ["Seller Note B",
                  f"  Principal:              {money(note_b['amount'])}, subject to the revenue test at month 24",
                  f"  Interest accrued:       {money(acc)} at {note_b['rate']:.0%} simple since close",
                  f"  Standby ends:           {long_date(note_b['schedule']['standby_end'])}",
                  f"  First installment:      {long_date(note_b['next_date'])} per the note. The purchase agreement states a different date; we will confirm which controls before the standby period ends.", ""]
    if consulting:
        lines += ["Consulting Agreement",
                  f"  Paid to date:           {money(sv['consulting_payments_made'] * 6000)} ({sv['consulting_payments_made']} monthly fees)",
                  f"  Next payment:           {money(6000)} on {long_date(consulting['next_date'])}",
                  f"  Remaining after that:   {12 - sv['consulting_payments_made'] - 1} monthly fees through July 2027", ""]
    if holdback:
        lines += ["Holdback",
                  f"  Amount held:            {money(holdback['amount'])} by Ashcroft Lowe LLP",
                  f"  Working capital true-up: settled {long_date(sv['nwc_settled_on'])}, adjustment {money(sv['nwc_adjustment'])}" if sv["nwc_settled"] else "  Working capital true-up: not yet settled",
                  f"  Release:                Due {long_date(holdback['next_date'])}. Release instruction awaiting buyer approval.", ""]
    lines += ["This statement is informational. It is not a demand for payment and it does not change the terms of any instrument.",
              "RolledCo does not hold or move funds."]
    drafts.append({"id": "statement-kowalski", "kind": "Seller Statement", "title": f"Statement for {seller}",
                   "to": seller, "approved_label": "Approved, ready for buyer to send", "body": "\n".join(lines)})

    months = ledger.read_pnl()
    q4 = [m for m in months if m["month"] in ("2026-10", "2026-11", "2026-12")]
    q4_rev = sum(m["revenue"] for m in q4)
    q4_ni = sum(m["net_income"] for m in q4)
    ytd_rev = sum(m["revenue"] for m in months)
    ytd_ni = sum(m["net_income"] for m in months)
    sba = obs.get("sba-loan")
    bal = ledger.sba_balance(sba, TODAY) if sba else 0
    drafts.append({
        "id": "lender-q4", "kind": "Lender Package Cover Note", "title": "Quarterly Package, Q4 2026",
        "to": f"Priya Raman, Vice President, SBA Lending, {deal['lender']}",
        "approved_label": "Approved, ready for buyer to send",
        "body": "\n".join([
            f"To:       Priya Raman, Vice President, SBA Lending, {deal['lender']}",
            f"From:     {deal['buyer_owner']}, Managing Member, {deal['buyer']}",
            f"Date:     {long_date(TODAY.isoformat())}",
            "Re:       Quarterly reporting package, quarter ended December 31, 2026, due February 14, 2027",
            "",
            "Dear Ms. Raman,",
            "",
            "Enclosed is the quarterly reporting package required by Section 6(a) of the commitment letter dated June 18, 2026.",
            "",
            "Enclosures",
            "  1. Balance sheet as of December 31, 2026",
            "  2. Income statement, quarter ended December 31, 2026 and period from closing through year end",
            "  3. Accounts receivable aging as of December 31, 2026",
            "  4. Managing member certification",
            "",
            "Summary",
            f"  Q4 revenue:                     {money(q4_rev)}",
            f"  Q4 net income:                  {money(q4_ni)}",
            f"  Revenue since close:            {money(ytd_rev)}",
            f"  Net income since close:         {money(ytd_ni)}",
            f"  SBA loan balance, estimated:    {money(bal)} after {sv['sba_payments_made']} payments",
            "  Seller note payments:           None. Both notes remain on standby under the Standby Creditor's Agreement.",
            "",
            "Please let me know if the bank needs anything further.",
            "",
            f"{deal['buyer_owner']}",
        ]),
    })

    out = []
    for d in drafts:
        st = state.get("outbox", {}).get(d["id"], {})
        d["status"] = st.get("status", "Draft")
        d["body"] = st.get("body", d["body"])
        d["approved_at"] = st.get("approved_at")
        out.append(d)
    return out, led


# ---------------------------------------------------------------- lender reporting
def reporting_items(data, state):
    sv = state.get("servicing", default_servicing())
    items = []
    for ob in data["obligations"]:
        if ob["type"] != "lender_reporting":
            continue
        for e in ledger.build_events(ob):
            d = date.fromisoformat(e["date"])
            if d < date(TODAY.year, TODAY.month - 3 if TODAY.month > 3 else 1, 1) or d > ledger.add_months(TODAY, 12):
                continue
            period = describe_period(ob, d)
            if d < TODAY:
                status, detail = "Submitted", f"Submitted {long_date(sv['q3_report_submitted_on'])}"
            elif ob["id"] == "lender-quarterly" and (d - TODAY).days <= 45:
                status, detail = "In Progress", "Cover note drafted in the Outbox"
            else:
                status, detail = "Upcoming", f"{(d - TODAY).days} days away"
            items.append({"instrument": ob["instrument"], "period": period, "due": e["date"], "status": status,
                          "detail": detail, "rule": ob["schedule"]["day_rule"], "days": (d - TODAY).days})
    return sorted(items, key=lambda x: x["due"])


def describe_period(ob, due):
    if ob["id"] == "lender-quarterly":
        qend = ledger.add_months(date(due.year, due.month, 1), -1)
        q = (qend.month - 1) // 3 + 1
        return f"Q{q} {qend.year}"
    if ob["id"] == "lender-annual-tax":
        return f"FY{due.year - 1} federal return"
    return f"{due.year - 1} personal return, Dana Whitfield"


# ---------------------------------------------------------------- seller view
def seller_view(data, state):
    deal = data["deal"]
    led = ledger.build_ledger(data, TODAY, state)
    seller_rows = [r for r in led["rows"] if r["counterparty"].startswith(deal["seller"])]
    upcoming = []
    for r in seller_rows:
        for e in r["events"]:
            if date.fromisoformat(e["date"]) >= TODAY and e["amount"]:
                upcoming.append(e)
    upcoming.sort(key=lambda e: e["date"])
    by_cp = next((c for c in led["totals"]["by_counterparty"] if c["counterparty"] == deal["seller"]), None)
    return {"seller": deal["seller"], "buyer": deal["buyer"], "rows": seller_rows, "upcoming": upcoming[:12],
            "outstanding": by_cp, "today": TODAY.isoformat()}


# ---------------------------------------------------------------- api
def text_summary():
    """Plain text view of the whole demo, for readers that do not run JavaScript."""
    data = load_data()
    state = load_state()
    drafts, led = build_drafts(data, state)
    T = led["totals"]
    deal = data["deal"]
    out = [f"RolledCo servicing demo. Demo with synthetic data. RolledCo does not hold or move funds.",
           f"As of {long_date(TODAY.isoformat())}. {deal['buyer']} ({deal['buyer_owner']}) acquired {deal['seller_entity']} "
           f"from {deal['seller']} for {money(deal['purchase_price'])} on {long_date(deal['close_date'])}. Lender: {deal['lender']}.",
           "", f"CLOSING BINDER ({len(data['documents'])} documents)"]
    out += [f"  {d['title']} ({d['file']}, {d['pages']} pages)" for d in data["documents"]]
    out += ["", "REVIEW (extracted obligations)"]
    for o in data["obligations"]:
        amt = money(o["amount"]) if o.get("amount") is not None else "non-monetary"
        out.append(f"  {o['instrument']} | {o['counterparty']} | {amt} | next {long_date(o['next_date']) if o.get('next_date') else 'contingent'} | confidence {o['confidence']:.0%}")
        out.append(f"    Source: {o['source']['document']} page {o['source']['page']}, {o['source']['section']}: \"{o['source']['quote']}\"")
        for c in o.get("conflicts", []):
            out.append(f"    FLAG ({c['kind']}): {c['title']}. {c['description']} Cited: {c['with_document']} page {c['page']}: \"{c['quote']}\"")
    out += ["", "LEDGER",
            f"  Due this month: {money(T['this_month']['total'])} (" + "; ".join(f"{e['instrument']} {long_date(e['date'])} {money(e['amount'])}" for e in T['this_month']['items']) + ")",
            f"  Due next 12 months: {money(T['next_12']['total'])} across {T['next_12']['count']} payments",
            "  Outstanding by counterparty: " + "; ".join(f"{c['counterparty']} {money(c['total'])}" for c in T["by_counterparty"])]
    for r in led["rows"]:
        standby = f", standby {long_date(r['standby'][0])} to {long_date(r['standby'][1])}" if r.get("standby") else ""
        first = r["events"][0] if r["events"] else None
        out.append(f"  {r['instrument']}: {len(r['events'])} events{standby}" + (f", first {long_date(first['date'])}" + (f" {money(first['amount'])}" if first.get("amount") is not None else "") if first else ""))
    me = ledger.month_end(data, TODAY)
    out += ["", f"MONITOR: Seller Note A payment check: {ledger.schedule_check(data, 'note-a', TODAY)['headline']}",
            f"  Month-end run ({me['status']}):"]
    out += [f"    {s['label']}: {money(s['value'])}" for s in me["steps"]]
    out += ["  Lender reporting:"] + [f"    {r['period']}, {r['instrument']}, due {long_date(r['due'])}, {r['status']}" for r in reporting_items(data, state)]
    out += ["", "OUTBOX"] + [f"  {d['kind']}: {d['title']} (to {d['to']}) status: {d['status']}" for d in drafts]
    out += ["", "Routes: / (app), /summary (this text), /api/state (JSON), /binder/<file>.pdf (documents)."]
    return "\n".join(out)


@app.get("/", response_class=HTMLResponse)
def index():
    html = (STATIC / "index.html").read_text()
    # Readers without JavaScript (and link previews) get the full text summary inline.
    import html as html_mod
    block = f'<div id="prerender" hidden><pre>{html_mod.escape(text_summary())}</pre></div>\n<noscript><pre>{html_mod.escape(text_summary())}</pre></noscript>'
    return html.replace("<script src=", block + "\n  <script src=", 1)


@app.get("/summary", response_class=PlainTextResponse)
def summary():
    return text_summary()


@app.get("/api/state")
def api_state():
    data = load_data()
    state = load_state()
    drafts, led = build_drafts(data, state)
    obligations = []
    for ob in data["obligations"]:
        o = dict(ledger.apply_edits(ob, state))
        o["review"] = state.get("review", {}).get(ob["id"], {"decision": None})
        obligations.append(o)
    return {
        "today": TODAY.isoformat(),
        "model": data.get("model", MODEL),
        "extraction_source": data.get("source", "cache"),
        "generated_at": data.get("generated_at"),
        "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
        "deal": data["deal"],
        "documents": data["documents"],
        "obligations": obligations,
        "ledger": led,
        "month_end": ledger.month_end(data, TODAY),
        "reporting": reporting_items(data, state),
        "outbox": drafts,
        "seller_view": seller_view(data, state),
        "servicing": state.get("servicing", default_servicing()),
    }


class ReviewBody(BaseModel):
    decision: str | None = None
    edits: dict | None = None


@app.post("/api/review/{ob_id}")
def api_review(ob_id: str, body: ReviewBody):
    state = load_state()
    entry = state.setdefault("review", {}).setdefault(ob_id, {})
    if body.decision:
        entry["decision"] = body.decision
    if body.edits is not None:
        entry["edits"] = {**entry.get("edits", {}), **body.edits}
    save_state(state)
    return {"ok": True, "review": entry}


class OutboxBody(BaseModel):
    action: str
    body: str | None = None


@app.post("/api/outbox/{draft_id}")
def api_outbox(draft_id: str, body: OutboxBody):
    state = load_state()
    data = load_data()
    drafts, _ = build_drafts(data, state)
    draft = next((d for d in drafts if d["id"] == draft_id), None)
    if not draft:
        raise HTTPException(404, "Unknown draft")
    entry = state.setdefault("outbox", {}).setdefault(draft_id, {})
    if body.action == "approve":
        entry["status"] = draft["approved_label"]
        entry["approved_at"] = TODAY.isoformat()
    elif body.action == "edit" and body.body is not None:
        entry["body"] = body.body
        entry["status"] = "Edited, awaiting approval"
    elif body.action == "unapprove":
        entry.pop("status", None)
        entry.pop("approved_at", None)
    save_state(state)
    return {"ok": True}


class ScheduleBody(BaseModel):
    obligation_id: str


@app.post("/api/schedule-payment")
def api_schedule(body: ScheduleBody):
    data = load_data()
    return ledger.schedule_check(data, body.obligation_id, TODAY)


@app.post("/api/month-end")
def api_month_end():
    return ledger.month_end(load_data(), TODAY)


@app.post("/api/extract/live")
def api_extract_live():
    if extract_job["running"]:
        return {"started": False, "reason": "already running"}
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return {"started": False, "reason": "ANTHROPIC_API_KEY is not set. Showing the cached extraction."}
    extract_job.update({"running": True, "lines": [], "exit_code": None})

    def run():
        proc = subprocess.Popen([sys.executable, str(ROOT / "extract.py")], cwd=str(ROOT),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            extract_job["lines"].append(line.rstrip())
        proc.wait()
        extract_job["exit_code"] = proc.returncode
        extract_job["running"] = False
        if proc.returncode == 0:
            st = load_state()
            st["review"] = {}
            save_state(st)

    threading.Thread(target=run, daemon=True).start()
    return {"started": True}


@app.get("/api/extract/status")
def api_extract_status():
    return extract_job


@app.post("/api/reset")
def api_reset():
    if CACHED.exists():
        try:
            shutil.copy(CACHED, OBLIGATIONS)
        except OSError:
            pass  # read-only host; the cached copy is what load_data falls back to anyway
    if STATE.exists():
        STATE.unlink()
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"RolledCo demo at http://localhost:{port}  (clock frozen at {TODAY.isoformat()})")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
