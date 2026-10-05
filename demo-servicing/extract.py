"""
RolledCo extraction. Reads every PDF in seed/binder, runs each one through the
Anthropic API, and writes structured obligations to data/obligations.json.

    ANTHROPIC_API_KEY=sk-ant-...  python extract.py
    ANTHROPIC_MODEL=claude-opus-5-5 python extract.py      # model override

The app ships with a cached data/obligations.json so the demo never depends on
a live call. This script overwrites that file. "Reset Demo" in the app restores
the cached copy from data/obligations.cached.json.

Four passes, named for the agents shown in the app:
    Reader       one API call per document, structured JSON out
    Compliance   one cross-document call that flags conflicts and missing terms
    Calculation  local Python, fills next dates and rounds amounts
    Servicing    writes the ledger file

Progress lines are printed with a STEP prefix so the app can stream them.
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

import anthropic
from pypdf import PdfReader

ROOT = Path(__file__).parent
BINDER = ROOT / "seed" / "binder"
OUT = ROOT / "data" / "obligations.json"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")
TODAY = os.environ.get("DEMO_TODAY", "2027-01-15")

DEAL = {
    "name": "Brightline Heating & Air",
    "buyer": "Northgate Acquisition LLC",
    "buyer_owner": "Dana Whitfield",
    "seller": "Ray Kowalski",
    "seller_entity": "Brightline Heating & Air LLC",
    "lender": "Harbor Federal Bank",
    "purchase_price": 2400000,
    "close_date": "2026-07-15",
}

DEAL_CONTEXT = """Northgate Acquisition LLC (buyer, owned by Dana Whitfield) acquired the assets of
Brightline Heating & Air LLC from Ray Kowalski on July 15, 2026 for $2,400,000, financed by an SBA 7(a)
loan from Harbor Federal Bank, buyer cash, and two seller notes. RolledCo is the servicing layer for
the money the buyer owes after close. It never holds or moves funds; it builds a ledger of obligations
and prepares instructions for a person to approve."""

SCHEDULE_SCHEMA = {
    "type": "object",
    "properties": {
        "frequency": {"type": "string", "enum": ["monthly", "quarterly", "annual", "one_time", "at_maturity"]},
        "first_date": {"type": ["string", "null"], "description": "ISO date of the first payment or deliverable, or null"},
        "last_date": {"type": ["string", "null"]},
        "count": {"type": ["integer", "null"], "description": "Number of payments or deliverables"},
        "day_rule": {"type": "string", "description": "Plain language rule for the due day, for example '15th of each month'"},
        "amount_each": {"type": ["number", "null"], "description": "Amount of each payment if fixed"},
        "standby_start": {"type": ["string", "null"], "description": "ISO date a no-payment standby period begins, or null"},
        "standby_end": {"type": ["string", "null"]},
    },
    "required": ["frequency", "first_date", "last_date", "count", "day_rule", "amount_each", "standby_start", "standby_end"],
    "additionalProperties": False,
}

OBLIGATION_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Short kebab-case id, stable across documents, e.g. note-a, consulting, bonus-herrera"},
        "instrument": {"type": "string", "description": "Name of the instrument, e.g. Seller Note A"},
        "type": {"type": "string", "enum": ["sba_loan", "seller_note", "consulting", "retention_bonus", "holdback", "adjustment", "lender_reporting", "other"]},
        "counterparty": {"type": "string"},
        "amount": {"type": ["number", "null"], "description": "Face or total amount in dollars, null if non-monetary or contingent"},
        "amount_text": {"type": "string"},
        "formula": {"type": "string", "description": "How the amount is computed, in plain language"},
        "rate": {"type": ["number", "null"], "description": "Annual interest rate as a decimal, if any"},
        "schedule": SCHEDULE_SCHEMA,
        "conditions": {"type": "array", "items": {"type": "string"}},
        "compliance_rules": {"type": "array", "items": {"type": "string"}, "description": "Rules that can block or gate a payment, e.g. 'no payment while the SBA loan is outstanding'"},
        "source": {
            "type": "object",
            "properties": {
                "document": {"type": "string"},
                "page": {"type": "integer"},
                "section": {"type": "string"},
                "quote": {"type": "string", "description": "Exact clause quoted from the document"},
            },
            "required": ["document", "page", "section", "quote"],
            "additionalProperties": False,
        },
        "confidence": {"type": "number", "description": "0 to 1"},
        "notes": {"type": "string"},
    },
    "required": ["id", "instrument", "type", "counterparty", "amount", "amount_text", "formula", "rate", "schedule",
                 "conditions", "compliance_rules", "source", "confidence", "notes"],
    "additionalProperties": False,
}

READER_SCHEMA = {
    "type": "object",
    "properties": {"obligations": {"type": "array", "items": OBLIGATION_SCHEMA}},
    "required": ["obligations"],
    "additionalProperties": False,
}

CONFLICT_SCHEMA = {
    "type": "object",
    "properties": {
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "obligation_id": {"type": "string"},
                    "kind": {"type": "string", "enum": ["conflict", "missing_term"]},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "with_document": {"type": "string"},
                    "page": {"type": "integer"},
                    "section": {"type": "string"},
                    "quote": {"type": "string"},
                    "confidence_after": {"type": "number"},
                },
                "required": ["obligation_id", "kind", "title", "description", "with_document", "page", "section", "quote", "confidence_after"],
                "additionalProperties": False,
            },
        },
        "merged_ids": {
            "type": "array",
            "description": "Pairs of ids that describe the same obligation; the first id is kept",
            "items": {"type": "array", "items": {"type": "string"}},
        },
    },
    "required": ["conflicts", "merged_ids"],
    "additionalProperties": False,
}

READER_SYSTEM = f"""You read closing documents for a small business acquisition and extract every payment or
deliverable the BUYER owes after close. {DEAL_CONTEXT}

Extract obligations only where this document is the primary source. A letter of intent and a funds flow
memo summarize terms that live in other documents; from those, extract only obligations that no other
document would carry (for the LOI, usually nothing; for the funds flow, the SBA loan payment if the lender
letter is not in the binder). Quote the exact clause. Use the page markers in the text for the page number.
Use these ids where they apply: sba-loan, note-a, note-b, consulting, bonus-<lastname>, holdback,
nwc-trueup, lender-quarterly, lender-annual-tax, lender-guarantor-returns. Confidence reflects how
completely the document states amount, schedule and conditions. Today is {TODAY}."""

COMPLIANCE_SYSTEM = f"""You are the compliance pass over obligations extracted from a closing binder. {DEAL_CONTEXT}
You receive every extracted obligation with its source quote, plus the full text of every document. Find:
1. Conflicts: the same term stated differently in two documents (dates, amounts, rates, parties).
2. Missing terms: a protection that appears in sibling documents of the same kind but is absent from one
   (for example a forfeiture clause present in two bonus letters and missing from the third).
3. Duplicates: two ids that describe the same obligation.
Cite the other document, its page and the exact quote. Lower the confidence of a flagged obligation."""


def log(step, msg):
    print(f"STEP {step}: {msg}", flush=True)


def read_pdf(path):
    reader = PdfReader(str(path))
    parts = []
    for i, page in enumerate(reader.pages, start=1):
        parts.append(f"[[PAGE {i}]]\n{page.extract_text()}")
    return len(reader.pages), "\n\n".join(parts)


def call_json(client, system, user, schema):
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("The model declined this request.")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def main():
    client = anthropic.Anthropic()
    files = sorted(BINDER.glob("*.pdf"))
    documents, texts, obligations = [], {}, []

    for f in files:
        pages, text = read_pdf(f)
        texts[f.name] = text
        documents.append({"file": f.name, "title": f.stem[3:].replace("_", " ").title(), "kind": "Document",
                          "dated": None, "pages": pages})
        log("Reader", f"Reading {f.name} ({pages} pages)")
        result = call_json(client, READER_SYSTEM,
                           f"Document file name: {f.name}\n\n{text}", READER_SCHEMA)
        for ob in result["obligations"]:
            ob["source"]["document"] = f.name
            ob["conflicts"] = []
            obligations.append(ob)
        log("Reader", f"{f.name}: {len(result['obligations'])} obligation(s)")

    log("Compliance", f"Cross-checking {len(obligations)} obligations across {len(files)} documents")
    corpus = "\n\n".join(f"===== {name} =====\n{t}" for name, t in texts.items())
    compliance = call_json(
        client, COMPLIANCE_SYSTEM,
        "EXTRACTED OBLIGATIONS\n" + json.dumps(obligations, indent=1) + "\n\nDOCUMENTS\n" + corpus,
        CONFLICT_SCHEMA)

    for keep, *drop in compliance["merged_ids"]:
        obligations = [o for o in obligations if o["id"] not in drop]
        log("Compliance", f"Merged {', '.join(drop)} into {keep}")
    by_id = {o["id"]: o for o in obligations}
    for c in compliance["conflicts"]:
        ob = by_id.get(c["obligation_id"])
        if not ob:
            continue
        ob["conflicts"].append({k: c[k] for k in ("kind", "title", "description", "with_document", "page", "section", "quote")})
        ob["confidence"] = min(ob["confidence"], c["confidence_after"])
        log("Compliance", f"Flagged {ob['instrument']}: {c['title']}")

    log("Calculation", "Filling next dates and rounding amounts")
    from app.ledger import next_date_for  # local, no API
    for ob in obligations:
        ob["next_date"] = next_date_for(ob, date.fromisoformat(TODAY))
        if ob.get("amount") is not None:
            ob["amount"] = round(ob["amount"], 2)

    log("Servicing", f"Writing {OUT.relative_to(ROOT)}")
    OUT.write_text(json.dumps({
        "generated_at": date.today().isoformat(),
        "model": MODEL,
        "source": "live",
        "deal": DEAL,
        "documents": documents,
        "obligations": obligations,
    }, indent=2))
    log("Servicing", f"Done. {len(obligations)} obligations, "
                     f"{sum(len(o['conflicts']) for o in obligations)} flags.")


if __name__ == "__main__":
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("ANTHROPIC_API_KEY is not set. The app will keep using the cached extraction.", file=sys.stderr)
        sys.exit(2)
    sys.path.insert(0, str(ROOT))
    main()
