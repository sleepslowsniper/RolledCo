"""
RolledCo extraction script.

Reads every document in ./seed, runs each one through Claude
(claude-sonnet-4-6) to pull out obligations and recurring tasks, then runs a
second cross-document pass that flags conflicts and merges duplicates.

Writes ./data/obligations.json. No database.

Usage:
    ANTHROPIC_API_KEY=sk-ant-... python extract.py
    python extract.py --only engagement_letters/03_thistle_and_pine_cafe_engagement.txt
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-4-6"
ROOT = Path(__file__).parent
SEED = ROOT / "seed"
OUT = ROOT / "data" / "obligations.json"
TODAY = date.today().isoformat()

FIRM_CONTEXT = """The documents belong to Harbor Bookkeeping LLC, a 6-person
bookkeeping firm in Portsmouth, NH that was just acquired by a new owner. The
seller (Ruth Callahan) handed over a folder of documents. Staff: Ruth Callahan
(owner, leaving), Marcus Tran (senior bookkeeper), Priya Natarajan
(bookkeeper), Tom Bellweather (part-time bookkeeper), Jess Lindqvist
(admin/AP-AR), Danielle Okafor (payroll specialist, on leave until 12/1/2026).
Clients are the firm's bookkeeping clients. The firm itself also has
obligations (lease, payroll, subscriptions) - treat those as client="Harbor
Bookkeeping (firm)"."""

OBLIGATION_SCHEMA = {
    "type": "object",
    "properties": {
        "obligations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "client": {"type": "string", "description": "Client name, or 'Harbor Bookkeeping (firm)' for the firm's own obligations"},
                    "deliverable": {"type": "string", "description": "What must be done, specific, one line"},
                    "category": {"type": "string", "enum": ["client_deliverable", "tax_filing", "payroll", "billing", "contract", "firm_admin"]},
                    "cadence": {"type": "string", "enum": ["weekly", "biweekly", "semi-monthly", "monthly", "quarterly", "annually", "one-time", "unknown"]},
                    "cadence_detail": {"type": "string", "description": "e.g. 'by the 15th of the following month', 'every other Friday'"},
                    "next_due_date": {"type": ["string", "null"], "description": "YYYY-MM-DD, the next occurrence strictly after today, or null if it cannot be determined"},
                    "owner": {"type": ["string", "null"], "description": "Staff member named as responsible, or null"},
                    "fee": {"type": ["string", "null"], "description": "Fee or rate stated for this service, if any"},
                    "source_excerpt": {"type": "string", "description": "Short verbatim quote (under 200 chars) from the document supporting this"},
                    "confidence": {"type": "number", "description": "0.0-1.0. Lower when the cadence, date, or scope is ambiguous, informal, or inferred"},
                    "notes": {"type": "string", "description": "Anything the new owner should know: ambiguity, informality, missing paperwork, contract status"}
                },
                "required": ["client", "deliverable", "category", "cadence", "cadence_detail", "next_due_date", "owner", "fee", "source_excerpt", "confidence", "notes"],
                "additionalProperties": False
            }
        },
        "document_summary": {"type": "string", "description": "One or two sentences on what this document is and any red flags"}
    },
    "required": ["obligations", "document_summary"],
    "additionalProperties": False
}

RECONCILE_SCHEMA = {
    "type": "object",
    "properties": {
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "obligation_ids": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string", "description": "Plain-English description of what disagrees between which documents"}
                },
                "required": ["obligation_ids", "reason"],
                "additionalProperties": False
            }
        },
        "duplicates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "keep_id": {"type": "string"},
                    "merge_ids": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"}
                },
                "required": ["keep_id", "merge_ids", "reason"],
                "additionalProperties": False
            }
        },
        "missing_paperwork": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Clients or obligations referenced somewhere but with no supporting engagement letter or contract in the folder"
        }
    },
    "required": ["conflicts", "duplicates", "missing_paperwork"],
    "additionalProperties": False
}


def load_documents(only=None):
    docs = []
    for p in sorted(SEED.rglob("*.txt")):
        rel = p.relative_to(SEED).as_posix()
        if only and rel not in only:
            continue
        docs.append({"path": rel, "text": p.read_text()})
    return docs


def extract_one(client, doc):
    prompt = f"""Today is {TODAY}.

{FIRM_CONTEXT}

Read the document below and extract EVERY obligation, deliverable, deadline,
filing, or recurring task it creates for Harbor Bookkeeping. Include:
- recurring client deliverables (reconciliations, financial packages, payroll runs)
- tax and compliance filings the firm prepares or must remind the client about
- the firm's own billing of the client (invoicing cadence)
- contract-level obligations (renewals, notice deadlines, expiry, rate changes)
- the firm's own admin obligations if the document is about the firm itself

For invoices: extract the recurring billing obligation and any service that is
being billed. Note the fee and period.

Compute next_due_date as the next occurrence strictly after today. For "by the
15th of the following month" style deadlines, the next due date is the next
15th after today. For contract expiries or notice deadlines, use that date.
If an obligation is already overdue or expired, set next_due_date to null and
say so in notes with a lowered confidence.

Be specific. One obligation per deliverable. Do not invent services that the
document does not mention.

<document path="{doc['path']}">
{doc['text']}
</document>"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": OBLIGATION_SCHEMA}},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"Model refused on {doc['path']}")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def reconcile(client, obligations, docs):
    compact = [
        {k: o[k] for k in ("id", "client", "deliverable", "cadence", "cadence_detail", "next_due_date", "fee", "owner", "source_document", "notes")}
        for o in obligations
    ]
    sellers_note = next((d["text"] for d in docs if "how_we_do_things" in d["path"]), "")
    prompt = f"""Today is {TODAY}.

{FIRM_CONTEXT}

Below is the full list of obligations extracted document-by-document from the
handoff folder, followed by the seller's informal notes. Your job is a
cross-document reconciliation:

1. CONFLICTS: find obligations where two or more documents disagree on fee,
   cadence, deadline, or scope for the same client and service (e.g. an
   engagement letter says one fee and the invoices bill another; a letter says
   quarterly and an email says monthly; the seller's note says a different
   delivery day than the letter). Also flag obligations whose supporting
   contract has expired, or where a service is in the engagement letter but
   never appears on any invoice, or appears on invoices but not in any letter.
   Each conflict should reference every obligation id involved. Write the reason
   so a new owner can act on it, naming the documents.

2. DUPLICATES: the same obligation extracted from multiple documents (e.g.
   "monthly bookkeeping for Marlowe" from the engagement letter AND from an
   invoice). Pick the id with the most authoritative source (engagement letter
   > amendment > invoice > seller note) as keep_id and list the others as
   merge_ids. Do NOT merge things that are actually different deliverables.
   Do NOT merge across clients.

3. MISSING PAPERWORK: clients or services mentioned anywhere (especially the
   seller's note) that have no engagement letter or contract in the folder.

<obligations>
{json.dumps(compact, indent=1)}
</obligations>

<sellers_note>
{sellers_note}
</sellers_note>"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": RECONCILE_SCHEMA}},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Model refused reconciliation pass")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", help="Only process this seed path (repeatable)")
    ap.add_argument("--skip-reconcile", action="store_true")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. The app will still run using the committed data/obligations.json.", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic()
    docs = load_documents(args.only)
    print(f"Extracting from {len(docs)} documents with {MODEL} (today = {TODAY})")

    obligations, summaries = [], {}
    n = 0
    for doc in docs:
        print(f"  -> {doc['path']} ...", end=" ", flush=True)
        result = extract_one(client, doc)
        summaries[doc["path"]] = result["document_summary"]
        for o in result["obligations"]:
            n += 1
            o["id"] = f"OB-{n:03d}"
            o["source_document"] = doc["path"]
            o["conflict"] = {"flag": False, "reason": None}
            o["merged_from"] = []
            obligations.append(o)
        print(f"{len(result['obligations'])} obligations")

    recon = {"conflicts": [], "duplicates": [], "missing_paperwork": []}
    if not args.skip_reconcile and len(obligations) > 1:
        print("Reconciling across documents ...", end=" ", flush=True)
        recon = reconcile(client, obligations, docs)
        print(f"{len(recon['conflicts'])} conflicts, {len(recon['duplicates'])} duplicate groups")

    by_id = {o["id"]: o for o in obligations}

    # Apply duplicates: fold merge_ids into keep_id, keep all source docs.
    dropped = set()
    for d in recon["duplicates"]:
        keep = by_id.get(d["keep_id"])
        if not keep:
            continue
        for mid in d["merge_ids"]:
            m = by_id.get(mid)
            if not m or mid == keep["id"] or mid in dropped:
                continue
            keep["merged_from"].append({"id": mid, "source_document": m["source_document"], "fee": m.get("fee"), "cadence_detail": m.get("cadence_detail")})
            dropped.add(mid)

    # Apply conflicts (remapping any ids that were merged away).
    remap = {}
    for o in obligations:
        for mf in o["merged_from"]:
            remap[mf["id"]] = o["id"]
    for c in recon["conflicts"]:
        ids = {remap.get(i, i) for i in c["obligation_ids"]}
        for i in ids:
            o = by_id.get(i)
            if not o or i in dropped:
                continue
            o["conflict"]["flag"] = True
            o["conflict"]["reason"] = (o["conflict"]["reason"] + " | " if o["conflict"]["reason"] else "") + c["reason"]
            o["confidence"] = min(o["confidence"], 0.6)

    final = [o for o in obligations if o["id"] not in dropped]
    final.sort(key=lambda o: (o["next_due_date"] is None, o["next_due_date"] or "", o["client"]))

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": TODAY,
        "model": MODEL,
        "mode": "live",
        "document_summaries": summaries,
        "missing_paperwork": recon["missing_paperwork"],
        "obligations": final,
    }, indent=2))
    print(f"Wrote {len(final)} obligations to {OUT}")


if __name__ == "__main__":
    main()
