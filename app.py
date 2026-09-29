"""
RolledCo worklist server. FastAPI + one static HTML page. No database.

    python app.py            -> http://localhost:8000

Reads data/obligations.json (from extract.py, or the committed copy).
Review decisions and email drafts are stored in data/state.json.
Nothing here sends email or acts on anything; approval is the end state.
"""
import json
import os
import re
from datetime import date
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

ROOT = Path(__file__).parent
SEED = ROOT / "seed"
OBLIGATIONS = ROOT / "data" / "obligations.json"
STATE = ROOT / "data" / "state.json"
MODEL = "claude-sonnet-4-6"

app = FastAPI(title="RolledCo")

# Client contacts pulled from the seed documents, used for the To: line.
CONTACTS = {
    "Marlowe Family Dental": ("Dr. Elaine Marlowe (attn: Bev, office manager)", "office@marlowefamilydental.com"),
    "Cascade Plumbing & Heating": ("Dennis Kowalczyk", "dennis@cascadeplumbingnh.com"),
    "Thistle & Pine Cafe": ("Mira Sandoval", "mira@thistleandpine.com"),
    "Northgate Physical Therapy": ("Samuel Osei", "sam@northgatept.com"),
    "Redwood Property Management": ("Gloria Vance", "gloria@redwoodpm.com"),
    "Beacon Hill Law Group": ("Anita Desrosiers, Esq.", "adesrosiers@beaconhilllawgroup.com"),
    "Saltmarsh Landscaping & Snow": ("Rick Ferreira", "rick@saltmarshlandscaping.com"),
    "Orchard Street Veterinary Hospital": ("Dr. Hannah Whitcombe", "hwhitcombe@orchardstreetvet.com"),
    "Pinecrest Auto Body": ("Pinecrest Auto Body", "unknown"),
    "Harbor Bookkeeping (firm)": ("Counterparty (landlord / vendor / staff)", "unknown"),
}


def load_obligations():
    if not OBLIGATIONS.exists():
        raise HTTPException(500, "data/obligations.json not found. Run extract.py.")
    return json.loads(OBLIGATIONS.read_text())


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {}


def save_state(state):
    STATE.write_text(json.dumps(state, indent=2))


def merged():
    data = load_obligations()
    state = load_state()
    out = []
    for o in data["obligations"]:
        s = state.get(o["id"], {})
        row = dict(o)
        row.update(s.get("edits", {}))
        row["status"] = s.get("status", "pending")
        row["draft"] = s.get("draft")
        row["original"] = {k: o[k] for k in ("deliverable", "next_due_date", "owner", "cadence_detail")}
        out.append(row)
    out.sort(key=lambda o: (o["next_due_date"] is None, o["next_due_date"] or "", o["client"]))
    return data, out


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/obligations")
def get_obligations():
    data, rows = merged()
    return {
        "generated_at": data.get("generated_at"),
        "model": data.get("model"),
        "mode": data.get("mode"),
        "live_api": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "today": date.today().isoformat(),
        "missing_paperwork": data.get("missing_paperwork", []),
        "document_summaries": data.get("document_summaries", {}),
        "obligations": rows,
    }


class Decision(BaseModel):
    status: str | None = None  # pending | approved | rejected
    deliverable: str | None = None
    next_due_date: str | None = None
    owner: str | None = None
    cadence_detail: str | None = None


@app.patch("/api/obligations/{oid}")
def decide(oid: str, d: Decision):
    data, rows = merged()
    if not any(r["id"] == oid for r in rows):
        raise HTTPException(404, "unknown obligation")
    state = load_state()
    s = state.setdefault(oid, {})
    edits = s.setdefault("edits", {})
    for k in ("deliverable", "next_due_date", "owner", "cadence_detail"):
        v = getattr(d, k)
        if v is not None:
            edits[k] = v or None
    if d.status:
        if d.status not in ("pending", "approved", "rejected"):
            raise HTTPException(400, "bad status")
        s["status"] = d.status
        if d.status != "approved":
            s.pop("draft", None)
    save_state(state)
    return {"ok": True}


@app.post("/api/reset")
def reset():
    if STATE.exists():
        STATE.unlink()
    return {"ok": True}


@app.get("/seed/{path:path}")
def seed_doc(path: str):
    p = (SEED / path).resolve()
    if not str(p).startswith(str(SEED.resolve())) or not p.is_file():
        raise HTTPException(404, "no such document")
    return PlainTextResponse(p.read_text())


# ---------------------------------------------------------------- drafting

class DraftRequest(BaseModel):
    kind: str = "auto"  # auto | reminder | request


def pick_kind(o):
    text = f"{o['deliverable']} {o.get('notes') or ''} {o.get('cadence_detail') or ''}".lower()
    if re.search(r"collect|past-due|open invoice|late fee|balance", text):
        return "payment"
    if re.search(r"w-9|timesheet|receipt|square report|missing|send us|provide|cash jobs|deposit slip|scan", text):
        return "request"
    return "reminder"


def first_name(contact):
    base = contact.split(" (")[0].split(",")[0].strip()
    parts = base.split()
    if parts and parts[0].rstrip(".") in ("Dr", "Mr", "Ms", "Mrs"):
        return f"{parts[0]} {parts[-1]}"
    return parts[0] if parts else contact


def short_label(deliverable):
    s = re.split(r"[(,;]", deliverable)[0].strip().rstrip(".")
    return s if len(s) <= 70 else s[:67].rsplit(" ", 1)[0] + "…"


ASKS = [
    (r"w-9", "signed W-9s for each contractor you paid this year"),
    (r"timesheet", "approved timesheets by Wednesday at noon before each pay date"),
    (r"square", "the Square sales reports, or login access so we can pull them directly"),
    (r"receipt", "receipts for any transaction over $250 through the Dext app"),
    (r"cash job", "a note of any cash jobs (amount and job) so they get recorded"),
    (r"deposit slip", "deposit slips or photos from the bank account"),
    (r"scan|dor notice|letter", "a scan of the notice so we can confirm the filing schedule"),
]


def template_draft(o, kind):
    name, email = CONTACTS.get(o["client"], (o["client"], "unknown"))
    first = first_name(name)
    due = o.get("next_due_date")
    due_txt = fmt_long(due) if due else "the usual date"
    label = short_label(o["deliverable"])
    text = f"{o['deliverable']} {o.get('notes') or ''}".lower()
    sig = "Best regards,\n\nHarbor Bookkeeping LLC\n14 Bow Street, Suite 2B, Portsmouth NH\n(603) 555-0142"
    if kind == "payment":
        amounts = ", ".join(re.findall(r"INV-\d{4}-\d{4}[^,)]*", o["deliverable"])) or label
        subject = f"Open balance with Harbor Bookkeeping"
        body = (
            f"Hi {first},\n\n"
            f"I'm the new owner of Harbor Bookkeeping, and I'm going through every account as part of the transition. "
            f"Our records show the following still open:\n\n  {amounts}\n\n"
            f"If payment is already on its way, thank you, and please ignore this. If it's easier, you can pay by ACH "
            f"using the link on the invoice. Let me know if anything on the invoice looks off and I'll sort it out.\n\n{sig}"
        )
    elif kind == "request":
        ask = next((a for pat, a in ASKS if re.search(pat, text)), "anything still outstanding on your side (statements, reports, or approvals)")
        subject = f"Quick request: {label}"
        body = (
            f"Hi {first},\n\n"
            f"I'm the new owner of Harbor Bookkeeping, and I'm making sure nothing slips during the transition. "
            f"For the next round of the following, we're missing a few things from your side:\n\n"
            f"  {label}\n  Due: {due_txt}\n\n"
            f"Could you send over {ask} by the end of this week? If it's already in the shared folder, "
            f"just reply and let me know.\n\n{sig}"
        )
    else:
        subject = f"Upcoming: {label} ({due_txt})"
        body = (
            f"Hi {first},\n\n"
            f"A quick note from Harbor Bookkeeping. I'm the new owner and I'm confirming each recurring deliverable "
            f"with every client so nothing slips during the transition.\n\n"
            f"  {label}\n  Cadence: {o.get('cadence_detail') or o.get('cadence')}\n  Next due: {due_txt}\n\n"
            f"Nothing is needed from you unless something above looks wrong. If it does, just reply and I'll fix it.\n\n{sig}"
        )
    return {"to": f"{name} <{email}>", "subject": subject, "body": body, "kind": kind, "generated_by": "template"}


def fmt_long(d):
    y, m, dd = d.split("-")
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    return f"{months[int(m)-1]} {int(dd)}, {y}"


def claude_draft(o, kind, source_text):
    import anthropic

    client = anthropic.Anthropic()
    name, email = CONTACTS.get(o["client"], (o["client"], "unknown"))
    kind_instruction = {
        "request": "a short request for the documents or information the client still needs to provide",
        "reminder": "a short reminder that this deliverable is coming up and what the client can expect",
        "payment": "a short, friendly reminder about an open invoice balance",
        "auto": "either a missing-document request or a deliverable reminder, whichever fits the obligation better",
    }.get(kind, "a short reminder")
    prompt = f"""You are drafting an email on behalf of the NEW owner of Harbor Bookkeeping LLC, a small
bookkeeping firm in Portsmouth, NH, who just bought the firm from Ruth Callahan. Nothing will be
sent automatically; the owner will review and edit this draft.

Write {kind_instruction}. Under 150 words. Plain, warm, professional. No placeholders like [Name];
use the contact name given. Do not mention internal notes, conflicts between documents, fees the
client has not agreed to, or anything the client should not see. Sign as "Harbor Bookkeeping LLC".

Obligation:
{json.dumps({k: o.get(k) for k in ('client', 'deliverable', 'cadence', 'cadence_detail', 'next_due_date', 'notes')}, indent=1)}

Client contact: {name} <{email}>

Source document ({o['source_document']}):
<document>
{source_text}
</document>

Return JSON with keys: to, subject, body, kind ("request" or "reminder")."""
    schema = {
        "type": "object",
        "properties": {
            "to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
            "kind": {"type": "string", "enum": ["request", "reminder"]},
        },
        "required": ["to", "subject", "body", "kind"], "additionalProperties": False,
    }
    resp = client.messages.create(
        model=MODEL, max_tokens=4000, thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("model refused")
    text = next(b.text for b in resp.content if b.type == "text")
    out = json.loads(text)
    out["generated_by"] = MODEL
    return out


@app.post("/api/obligations/{oid}/draft")
def draft(oid: str, req: DraftRequest):
    data, rows = merged()
    o = next((r for r in rows if r["id"] == oid), None)
    if not o:
        raise HTTPException(404, "unknown obligation")
    if o["status"] != "approved":
        raise HTTPException(400, "only approved items can be drafted")
    kind = req.kind if req.kind != "auto" else pick_kind(o)
    src = SEED / o["source_document"]
    source_text = src.read_text() if src.exists() else ""
    d = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            d = claude_draft(o, req.kind, source_text)
        except Exception as e:  # fall back so the demo never stalls
            d = template_draft(o, kind)
            d["warning"] = f"API call failed ({type(e).__name__}); showing template draft"
    else:
        d = template_draft(o, kind)
    d["status"] = "draft"
    state = load_state()
    state.setdefault(oid, {})["draft"] = d
    save_state(state)
    return d


class DraftUpdate(BaseModel):
    subject: str | None = None
    body: str | None = None
    status: str | None = None  # draft | approved


@app.patch("/api/obligations/{oid}/draft")
def update_draft(oid: str, u: DraftUpdate):
    state = load_state()
    d = state.get(oid, {}).get("draft")
    if not d:
        raise HTTPException(404, "no draft")
    if u.subject is not None:
        d["subject"] = u.subject
    if u.body is not None:
        d["body"] = u.body
    if u.status in ("draft", "approved"):
        d["status"] = u.status
    save_state(state)
    return d


if __name__ == "__main__":
    print("RolledCo demo -> http://localhost:8000")
    print("Live Claude drafting:", "ON" if os.environ.get("ANTHROPIC_API_KEY") else "OFF (template drafts; set ANTHROPIC_API_KEY to enable)")
    uvicorn.run(app, host="127.0.0.1", port=8000)
