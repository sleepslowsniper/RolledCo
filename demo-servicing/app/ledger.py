"""
Ledger engine. Turns extracted obligations into dated events, totals, the
Note B month-end math, and the compliance check. Pure Python, no API calls.
"""
import calendar
import csv
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
PNL_DIR = ROOT / "seed" / "pnl"


# ---------------------------------------------------------------- date helpers
def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def last_business_day(y, m):
    d = date(y, m, calendar.monthrange(y, m)[1])
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def parse(s):
    return date.fromisoformat(s) if s else None


def long_date(s):
    if not s:
        return ""
    d = parse(s)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def pmt(principal, annual_rate, n):
    r = annual_rate / 12
    if r == 0:
        return principal / n
    return principal * r * (1 + r) ** n / ((1 + r) ** n - 1)


def simple_interest(principal, rate, start, end):
    return principal * rate * (end - start).days / 365


# ---------------------------------------------------------------- schedules
def event_dates(ob):
    s = ob["schedule"]
    first, last, count = parse(s.get("first_date")), parse(s.get("last_date")), s.get("count")
    if not first:
        return []
    freq = s.get("frequency")
    if freq in ("one_time", "at_maturity") or (count == 1):
        return [first]
    step = {"monthly": 1, "quarterly": 3, "annual": 12}.get(freq)
    if not step:
        return [first]
    dates = []
    if count:
        for i in range(count):
            d = add_months(first, step * i)
            if "last business day" in (s.get("day_rule") or ""):
                d = last_business_day(d.year, d.month)
            dates.append(d)
    elif last:
        d = first
        while d <= last:
            dates.append(d)
            d = add_months(first, step * len(dates))
    return dates


def note_b_terms(ob, adjusted_principal=None):
    """Contract and projected amortization for Seller Note B."""
    principal = ob.get("amount") or 120000
    rate = ob.get("rate") or 0.06
    s = ob["schedule"]
    standby_years = 2
    if s.get("standby_start") and s.get("standby_end"):
        a, b = parse(s["standby_start"]), parse(s["standby_end"])
        standby_years = ((b.year - a.year) * 12 + b.month - a.month) / 12
    n = s.get("count") or 36
    p = principal if adjusted_principal is None else adjusted_principal
    accrued = p * rate * standby_years
    balance = p + accrued
    return {"principal": p, "accrued_interest": accrued, "balance": balance,
            "installment": pmt(balance, rate, n), "count": n}


def build_events(ob):
    """Returns a list of {date, amount, label, kind} for one obligation."""
    kind = ob["type"]
    s = ob["schedule"]
    events = []
    dates = event_dates(ob)
    if kind == "seller_note" and s.get("frequency") == "at_maturity":
        start = parse(s.get("standby_start")) or parse(ob.get("close_date") or "2026-07-15")
        amount = (ob.get("amount") or 0) + simple_interest(ob.get("amount") or 0, ob.get("rate") or 0, start, dates[0])
        events.append({"date": dates[0].isoformat(), "amount": round(amount, 2),
                       "label": "Principal plus accrued interest at maturity", "kind": "payment"})
        return events
    if kind == "seller_note":
        terms = note_b_terms(ob)
        for i, d in enumerate(dates, start=1):
            events.append({"date": d.isoformat(), "amount": round(terms["installment"], 2),
                           "label": f"Installment {i} of {terms['count']}, contract terms before adjustment", "kind": "payment"})
        return events
    if kind == "retention_bonus":
        total = ob.get("amount") or 0
        n = len(dates) or 1
        base = round(total / n, 2)
        for i, d in enumerate(dates, start=1):
            amt = base if i < n else round(total - base * (n - 1), 2)
            events.append({"date": d.isoformat(), "amount": amt, "label": f"Tranche {i} of {n}", "kind": "payment"})
        return events
    if kind == "lender_reporting":
        for d in dates:
            events.append({"date": d.isoformat(), "amount": None, "label": ob["instrument"], "kind": "deliverable"})
        return events
    if kind == "adjustment":
        for d in dates:
            events.append({"date": d.isoformat(), "amount": None, "label": "Closing statement due", "kind": "deliverable"})
        return events
    each = s.get("amount_each")
    if each is None and ob.get("amount") is not None and dates:
        each = ob["amount"] / len(dates)
    for i, d in enumerate(dates, start=1):
        label = "Release to seller" if kind == "holdback" else f"Payment {i} of {len(dates)}"
        events.append({"date": d.isoformat(), "amount": round(each, 2) if each is not None else None,
                       "label": label, "kind": "payment"})
    return events


def next_date_for(ob, today):
    for e in build_events(ob):
        if parse(e["date"]) >= today:
            return e["date"]
    return None


def sba_balance(ob, today):
    """Principal remaining after the payments due on or before today."""
    principal = ob.get("amount") or 0
    rate = ob.get("rate") or 0
    payment = ob["schedule"].get("amount_each") or 0
    r = rate / 12
    bal = principal
    for e in build_events(ob):
        if parse(e["date"]) > today:
            break
        bal = bal * (1 + r) - payment
    return max(bal, 0)


# ---------------------------------------------------------------- ledger
def build_ledger(data, today, state):
    close = parse(data["deal"]["close_date"])
    horizon_start = date(close.year, close.month, 1)
    horizon_end = add_months(horizon_start, 122)
    rows, all_events = [], []
    for ob in data["obligations"]:
        if state.get("review", {}).get(ob["id"], {}).get("decision") == "reject":
            continue
        ob = apply_edits(ob, state)
        events = build_events(ob)
        for e in events:
            e["obligation_id"] = ob["id"]
            e["instrument"] = ob["instrument"]
            e["counterparty"] = ob["counterparty"]
        s = ob["schedule"]
        rows.append({
            "id": ob["id"], "instrument": ob["instrument"], "type": ob["type"],
            "counterparty": ob["counterparty"],
            "standby": [s.get("standby_start"), s.get("standby_end")] if s.get("standby_start") else None,
            "events": events, "flagged": bool(ob.get("conflicts")),
            "amount_text": ob.get("amount_text"),
        })
        all_events.extend(events)

    month_start = date(today.year, today.month, 1)
    month_end = add_months(month_start, 1)
    year_end = add_months(today, 12)

    def in_range(e, a, b):
        d = parse(e["date"])
        return a <= d < b and e["amount"] is not None

    this_month = [e for e in all_events if in_range(e, month_start, month_end)]
    next_12 = [e for e in all_events if in_range(e, today, year_end)]

    outstanding = {}
    for ob in data["obligations"]:
        if state.get("review", {}).get(ob["id"], {}).get("decision") == "reject":
            continue
        ob = apply_edits(ob, state)
        cp = short_counterparty(ob["counterparty"])
        val = outstanding_for(ob, today)
        if val:
            outstanding.setdefault(cp, {"counterparty": cp, "total": 0, "items": []})
            outstanding[cp]["total"] += val["amount"]
            outstanding[cp]["items"].append({"instrument": ob["instrument"], "amount": round(val["amount"], 2), "basis": val["basis"]})

    return {
        "horizon": [horizon_start.isoformat(), horizon_end.isoformat()],
        "today": today.isoformat(),
        "rows": rows,
        "totals": {
            "this_month": {"total": round(sum(e["amount"] for e in this_month), 2), "items": sorted(this_month, key=lambda e: e["date"])},
            "next_12": {"total": round(sum(e["amount"] for e in next_12), 2), "count": len(next_12)},
            "by_counterparty": sorted(outstanding.values(), key=lambda x: -x["total"]),
        },
    }


def short_counterparty(name):
    return name.split(",")[0].strip()


def outstanding_for(ob, today):
    kind = ob["type"]
    if kind == "sba_loan":
        return {"amount": sba_balance(ob, today), "basis": "principal balance after payments to date"}
    if kind == "seller_note":
        start = parse(ob["schedule"].get("standby_start")) or today
        acc = simple_interest(ob.get("amount") or 0, ob.get("rate") or 0, start, today)
        return {"amount": (ob.get("amount") or 0) + acc, "basis": "principal plus interest accrued to date"}
    if kind in ("consulting", "retention_bonus", "holdback"):
        remaining = [e for e in build_events(ob) if parse(e["date"]) >= today and e["amount"]]
        if not remaining:
            return None
        return {"amount": sum(e["amount"] for e in remaining), "basis": "remaining scheduled payments"}
    return None


def apply_edits(ob, state):
    edits = state.get("review", {}).get(ob["id"], {}).get("edits")
    if not edits:
        return ob
    ob = dict(ob)
    ob["schedule"] = dict(ob["schedule"])
    for k, v in edits.items():
        if k == "first_date":
            ob["schedule"]["first_date"] = v
            if ob["schedule"].get("count") and ob["schedule"].get("frequency") == "monthly":
                ob["schedule"]["last_date"] = add_months(parse(v), ob["schedule"]["count"] - 1).isoformat()
        elif k == "amount_each":
            ob["schedule"]["amount_each"] = v
        else:
            ob[k] = v
    return ob


# ---------------------------------------------------------------- month end
def read_pnl():
    months = []
    for f in sorted(PNL_DIR.glob("pnl_*.csv")):
        month = f.stem.replace("pnl_", "")
        rows = {}
        with open(f, newline="") as fh:
            for row in csv.reader(fh):
                if not row or row[0].startswith("#") or row[0] == "Line":
                    continue
                rows[row[0]] = float(row[1])
        months.append({"month": month, "file": f.name, "revenue": rows.get("Total revenue", 0),
                       "gross_profit": rows.get("Gross profit", 0), "net_income": rows.get("Net income", 0)})
    return months


def month_end(data, today):
    note_b = next((o for o in data["obligations"] if o["id"] == "note-b"), None)
    if not note_b:
        return {"error": "Seller Note B was not found in the extraction."}
    months = read_pnl()
    threshold, floor = 3100000, 60000
    principal = note_b.get("amount") or 120000
    rate = note_b.get("rate") or 0.06
    n_months = len(months)
    actual = sum(m["revenue"] for m in months)
    annualized = actual * 12 / n_months if n_months else 0
    shortfall = max(threshold - annualized, 0)
    unfloored = principal - shortfall
    adjusted = max(unfloored, floor)
    floor_applied = unfloored < floor
    contract = note_b_terms(note_b)
    projected = note_b_terms(note_b, adjusted)
    measurement = add_months(parse(data["deal"]["close_date"]), 24)
    measurement = date(measurement.year, measurement.month, calendar.monthrange(measurement.year, measurement.month)[1])
    steps = [
        {"label": f"Trailing revenue, {n_months} months of actuals ({months[0]['month']} to {months[-1]['month']})", "value": actual, "fmt": "money"},
        {"label": f"Annualized run rate (actuals times 12 divided by {n_months})", "value": annualized, "fmt": "money"},
        {"label": "Revenue threshold, Seller Note B Section 3", "value": threshold, "fmt": "money"},
        {"label": "Projected shortfall (threshold less run rate, not below zero)", "value": shortfall, "fmt": "money"},
        {"label": "Original principal", "value": principal, "fmt": "money"},
        {"label": "Principal less shortfall, dollar for dollar", "value": unfloored, "fmt": "money"},
        {"label": "Floor, Seller Note B Section 3", "value": floor, "fmt": "money"},
        {"label": "Projected adjusted principal" + (" (floor applies)" if floor_applied else " (above floor, no floor applied)"), "value": adjusted, "fmt": "money", "emphasis": True},
        {"label": f"Interest accrued during standby at {rate:.0%} simple for 2 years, recomputed on adjusted principal", "value": projected["accrued_interest"], "fmt": "money"},
        {"label": "Balance to amortize after standby", "value": projected["balance"], "fmt": "money"},
        {"label": f"Projected monthly installment, {projected['count']} payments at {rate:.0%}", "value": projected["installment"], "fmt": "money", "emphasis": True},
        {"label": "Contract installment before any adjustment, for comparison", "value": contract["installment"], "fmt": "money"},
    ]
    return {
        "as_of": today.isoformat(),
        "months": months,
        "threshold": threshold,
        "floor": floor,
        "measurement_date": measurement.isoformat(),
        "months_remaining": max((measurement.year - today.year) * 12 + measurement.month - today.month, 0),
        "annualized": annualized,
        "shortfall": shortfall,
        "adjusted_principal": adjusted,
        "floor_applied": floor_applied,
        "contract": contract,
        "projected": projected,
        "steps": steps,
        "status": "Tracking below threshold" if shortfall > 0 else "Tracking at or above threshold",
    }


# ---------------------------------------------------------------- compliance
def schedule_check(data, ob_id, today):
    ob = next((o for o in data["obligations"] if o["id"] == ob_id), None)
    if not ob:
        return {"allowed": False, "reason": "Unknown obligation."}
    s = ob["schedule"]
    sba = next((o for o in data["obligations"] if o["type"] == "sba_loan"), None)
    standby_end = parse(s.get("standby_end"))
    if standby_end and today <= standby_end:
        if ob["type"] == "seller_note" and s.get("frequency") == "at_maturity":
            balance = sba_balance(sba, today) if sba else None
            return {
                "allowed": False,
                "headline": "Blocked. Seller Note A is on full standby.",
                "reason": (f"No payment of principal or interest is permitted on Seller Note A while any amount remains "
                           f"outstanding under the SBA loan. The loan balance today is about ${balance:,.0f} and its final "
                           f"payment is scheduled for {long_date(sba['schedule']['last_date'])}. Interest keeps accruing at "
                           f"{ob.get('rate', 0):.0%} and is paid with principal at maturity."),
                "citations": [
                    {"document": ob["source"]["document"], "page": ob["source"]["page"], "section": ob["source"]["section"], "quote": ob["source"]["quote"]},
                    {"document": "05_standby_creditor_agreement.pdf", "page": 1, "section": "Section 2(a), Permitted Payments",
                     "quote": "Seller Note A. Full standby. No payments of principal or interest are permitted for the life of the SBA Loan. Interest may accrue."},
                ],
                "next_allowed": ob.get("next_date"),
            }
        return {
            "allowed": False,
            "headline": f"Blocked. {ob['instrument']} is in its standby period.",
            "reason": (f"No payment is permitted until the standby period ends on {long_date(standby_end.isoformat())}. "
                       f"The first scheduled installment is {long_date(ob.get('next_date'))}."),
            "citations": [{"document": ob["source"]["document"], "page": ob["source"]["page"], "section": ob["source"]["section"], "quote": ob["source"]["quote"]}],
            "next_allowed": ob.get("next_date"),
        }
    if ob["type"] == "lender_reporting":
        return {"allowed": False, "headline": "Nothing to pay.", "reason": f"{ob['instrument']} is a deliverable, not a payment. Track it under Lender Reporting.", "citations": []}
    nxt = next((e for e in build_events(ob) if parse(e["date"]) >= today and e["amount"]), None)
    if not nxt:
        return {"allowed": False, "headline": "No payment due.", "reason": "There is no remaining scheduled payment on this instrument.", "citations": []}
    return {
        "allowed": True,
        "headline": f"Allowed. Next payment on {ob['instrument']} can be scheduled.",
        "reason": f"${nxt['amount']:,.2f} to {ob['counterparty']} due {long_date(nxt['date'])}. A draft payment instruction is in the Outbox for approval.",
        "citations": [{"document": ob["source"]["document"], "page": ob["source"]["page"], "section": ob["source"]["section"], "quote": ob["source"]["quote"]}],
        "event": nxt,
    }
