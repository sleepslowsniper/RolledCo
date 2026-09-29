#!/usr/bin/env python3
"""
enrich_contacts.py - merge Perplexity people exports, enrich via AI Ark, write CSV.

    pip install requests
    AIARK_API_KEY=... python enrich_contacts.py                 # CSVs in ./input
    python enrich_contacts.py --input path/to/csvs --dry-run   # merge/dedupe only

Steps
  1. Read every *.csv in --input, normalize columns to
     name, title, company, linkedin_url, source_variant, dedupe on name+company.
  2. Enrich each row with AI Ark (LinkedIn URL first, name+company fallback).
     Rate-limited, retries on 429/5xx, responses cached in .aiark_cache.json.
  3. Write contacts_enriched.csv with email, email_confidence, phone, enrichment_status.
  4. Print a summary.

Nothing is sent to anyone. Only AI Ark is called, and only when a key is set.
"""
import argparse
import csv
import glob
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

BASE_URL = os.environ.get("AIARK_BASE_URL", "https://api.ai-ark.com/api/developer-portal")
API_KEY = os.environ.get("AIARK_API_KEY", "")
CACHE_FILE = Path(".aiark_cache.json")
OUT_FILE = Path("contacts_enriched.csv")

# AI Ark default limit is 5 req/s per key. Stay well under it.
MIN_SECONDS_BETWEEN_CALLS = 0.35
MAX_RETRIES = 5

# ----------------------------------------------------------------- step 1: merge

# Header aliases, lower-cased and stripped of punctuation. First match wins.
ALIASES = {
    "name": ["name", "full name", "fullname", "person", "contact"],
    "title": ["title", "current title", "role", "position", "job title"],
    "company": ["company", "company holdco", "company / holdco", "organization", "organisation", "firm", "school", "employer", "business"],
    "linkedin_url": ["linkedin_url", "linkedin", "linkedin url", "linkedin profile", "linkedin or faculty page", "profile url", "url"],
}


def norm_header(h):
    h = (h or "").strip().lower()
    h = re.sub(r"[^a-z0-9/ ]+", " ", h)
    return re.sub(r"\s+", " ", h).strip()


def map_columns(headers):
    normed = {norm_header(h): h for h in headers}
    mapping = {}
    for target, options in ALIASES.items():
        for opt in options:
            if opt in normed:
                mapping[target] = normed[opt]
                break
        if target not in mapping:  # fuzzy: header contains the word
            for nh, raw in normed.items():
                if target.split("_")[0] in nh:
                    mapping[target] = raw
                    break
    return mapping


def clean_name(s):
    s = (s or "").strip()
    s = re.sub(r"\((not found|n/?a)\)", "", s, flags=re.I)
    s = re.sub(r"linkedin$", "", s, flags=re.I)              # "Jane Doelinkedin" (Perplexity link-text bleed)
    s = re.sub(r",\s*(CFA|CPA|MBA|PhD|Jr\.?|Sr\.?|III|II)\b.*$", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" ,")
    return s


def clean_company(s):
    s = (s or "").strip()
    if re.fullmatch(r"(same as above|same|n\.?a\.?|—|-)?", s, flags=re.I):
        return ""
    return re.sub(r"\s+", " ", s)


def clean_linkedin(s):
    s = (s or "").strip()
    m = re.search(r"(https?://)?(www\.)?linkedin\.com/in/[A-Za-z0-9\-_%\.]+/?", s)
    if not m:
        return ""
    url = m.group(0)
    if not url.startswith("http"):
        url = "https://" + url
    url = url.replace("http://", "https://").replace("https://linkedin.com", "https://www.linkedin.com")
    return url.rstrip("/")


NICKNAMES = {"rob": "robert", "bob": "robert", "mike": "michael", "matt": "matthew", "tom": "thomas", "jim": "james",
             "dave": "david", "steve": "steven", "chris": "christopher", "nick": "nicholas", "dan": "daniel",
             "greg": "gregory", "rich": "richard", "rick": "richard", "andy": "andrew", "will": "william", "bill": "william"}


def dedupe_key(name, company):
    def fold(x):
        x = unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode()
        x = re.sub(r"\(.*?\)", "", x)                 # drop "(Kirkland, WA)" style parentheticals
        x = re.sub(r"[^a-z0-9 ]+", " ", x.lower())
        x = re.sub(r"\b(the|llc|inc|co|corp|ltd|group|holdings|holdco)\b", " ", x)
        return re.sub(r"\s+", " ", x).strip()
    parts = fold(name).split()
    if parts:
        parts[0] = NICKNAMES.get(parts[0], parts[0])
    n = " ".join(p for p in parts if len(p) > 1)          # drop middle initials
    c = fold(company).split(" / ")[0].split(" plus ")[0]
    return (n, c)


def variant_letter(path, index):
    m = re.search(r"\b(?:variant|source)?[ _-]?([A-D])\b", Path(path).stem, flags=re.I)
    return m.group(1).upper() if m else "ABCD"[index] if index < 4 else str(index + 1)


def merge(input_dir):
    files = sorted(glob.glob(os.path.join(input_dir, "*.csv")))
    if not files:
        sys.exit(f"No CSVs found in {input_dir}")
    rows, seen, per_file = [], {}, []
    for i, f in enumerate(files):
        variant = variant_letter(f, i)
        with open(f, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            cols = map_columns(reader.fieldnames or [])
            missing = [k for k in ("name", "title", "company") if k not in cols]
            n_in = n_kept = 0
            for r in reader:
                n_in += 1
                name = clean_name(r.get(cols.get("name", ""), ""))
                if not name:
                    continue
                company = clean_company(r.get(cols.get("company", ""), ""))
                row = {
                    "name": name,
                    "title": (r.get(cols.get("title", ""), "") or "").strip(),
                    "company": company,
                    "linkedin_url": clean_linkedin(r.get(cols.get("linkedin_url", ""), "")),
                    "source_variant": variant,
                }
                key = dedupe_key(name, company)
                if key in seen:
                    keep = rows[seen[key]]
                    # keep the first row, but backfill blanks from the duplicate
                    for k in ("title", "company", "linkedin_url"):
                        if not keep[k] and row[k]:
                            keep[k] = row[k]
                    if variant not in keep["source_variant"].split("+"):
                        keep["source_variant"] += "+" + variant
                    continue
                seen[key] = len(rows)
                rows.append(row)
                n_kept += 1
            per_file.append((variant, Path(f).name, n_in, n_kept, missing, cols))
    return rows, per_file


# ------------------------------------------------------------- step 2: enrich

class AIArk:
    def __init__(self, key, cache_file=CACHE_FILE):
        self.key = key
        self.cache_file = cache_file
        self.cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        self.last_call = 0.0
        self.calls = 0
        self.session = requests.Session()
        self.session.headers.update({"X-TOKEN": key, "Content-Type": "application/json"})

    def _save(self):
        self.cache_file.write_text(json.dumps(self.cache, indent=1))

    def post(self, path, body):
        """POST with cache, polite rate limit, and retry on 429/5xx. Returns (status, json_or_none)."""
        ck = hashlib.sha1(f"{path}|{json.dumps(body, sort_keys=True)}".encode()).hexdigest()
        if ck in self.cache:
            return self.cache[ck]["status"], self.cache[ck]["data"]
        for attempt in range(MAX_RETRIES):
            wait = MIN_SECONDS_BETWEEN_CALLS - (time.time() - self.last_call)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self.session.post(BASE_URL + path, json=body, timeout=60)
            except requests.RequestException as e:
                if attempt == MAX_RETRIES - 1:
                    return 0, {"error": str(e)}
                time.sleep(2 ** attempt)
                continue
            self.last_call = time.time()
            self.calls += 1
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 30)
                print(f"    {resp.status_code} on {path}, retrying in {delay:.0f}s", file=sys.stderr)
                time.sleep(delay)
                continue
            try:
                data = resp.json()
            except ValueError:
                data = {"raw": resp.text[:500]}
            # Cache every definitive answer (200, 404 = no data, 400 = bad input) so reruns don't re-bill.
            if resp.status_code in (200, 400, 404):
                self.cache[ck] = {"status": resp.status_code, "data": data}
                self._save()
            return resp.status_code, data
        return 429, {"error": "gave up after retries"}

    # -- endpoints

    def export_by_linkedin(self, url):
        """v2 export: 200 with data=null when nothing found (0 credits). 1 credit when an email is found."""
        return self.post("/v2/people/export/single", {"url": url})

    def export_by_id(self, person_id):
        return self.post("/v2/people/export/single", {"id": person_id})

    def search_person(self, name, company):
        """People search by full name + company name. 0.5 credit per returned result; ask for 3."""
        body = {
            "contact": {"fullName": {"mode": "SMART", "include": [name]}},
            "account": {"name": {"mode": "SMART", "include": [company]}},
            "page": 0, "size": 3,
        }
        return self.post("/v1/people", body)

    def mobile_phone(self, linkedin=None, name=None, domain=None):
        """5 credits when a number is found, 0 on 404."""
        body = {"linkedin": linkedin} if linkedin else {"name": name, "domain": domain}
        return self.post("/v1/people/mobile-phone-finder", body)


def unwrap(data):
    """v2 endpoints wrap as {status, error, data}; v1 return the object directly."""
    if isinstance(data, dict) and "data" in data and ("status" in data or "error" in data):
        return data["data"]
    return data


def pick_email(person):
    """Return (address, confidence) from an AI Ark person object, or ('', '')."""
    if not isinstance(person, dict):
        return "", ""
    email = person.get("email") or {}
    outputs = email.get("output") if isinstance(email, dict) else None
    if isinstance(email, list):
        outputs = email
    if not outputs:
        return "", ""
    # prefer VALID, then anything non-free, then first
    ranked = sorted(outputs, key=lambda o: (
        0 if str(o.get("status", "")).upper() == "VALID" else 1,
        1 if o.get("free") else 0,
    ))
    best = ranked[0]
    status = str(best.get("status") or email.get("status") or "").upper() if isinstance(email, dict) else str(best.get("status", "")).upper()
    conf = {"VALID": "high", "CATCH_ALL": "medium", "CATCHALL": "medium", "ACCEPT_ALL": "medium",
            "UNKNOWN": "low", "RISKY": "low", "INVALID": "none"}.get(status, status.lower() or "unknown")
    return best.get("address", ""), conf


def person_matches(person, name, company):
    """Sanity check a search hit: last name must match; company should overlap if we have one."""
    prof = person.get("profile") or {}
    full = f"{prof.get('first_name', '')} {prof.get('last_name', '')}".strip().lower() or str(prof.get("full_name", "")).lower()
    last = name.split()[-1].lower()
    if last not in full:
        return False
    if company:
        names = [g.get("company", {}).get("name", "") for g in person.get("position_groups", []) if isinstance(g, dict)]
        names.append((person.get("company") or {}).get("name", "") if isinstance(person.get("company"), dict) else "")
        ckey = dedupe_key("", company)[1].split()[0] if dedupe_key("", company)[1] else ""
        if ckey and not any(ckey in dedupe_key("", n)[1] for n in names if n):
            return False
    return True


def enrich_row(api, row, want_phone=True):
    """Fill email/email_confidence/phone/enrichment_status on the row in place."""
    row.update({"email": "", "email_confidence": "", "phone": "", "enrichment_status": ""})
    person, matched_by, linkedin = None, "", row["linkedin_url"]

    if linkedin:
        status, data = api.export_by_linkedin(linkedin)
        person = unwrap(data) if status == 200 else None
        matched_by = "linkedin" if person else ""
        if status not in (200, 404):
            row["enrichment_status"] = f"error_{status}"

    if not person and row["name"] and row["company"]:
        status, data = api.search_person(row["name"], row["company"])
        hits = []
        if status == 200:
            body = unwrap(data) or data
            hits = body.get("results") or body.get("data") or body.get("content") or body.get("people") or []
            if isinstance(hits, dict):
                hits = hits.get("results") or hits.get("content") or []
        for h in hits:
            if isinstance(h, dict) and person_matches(h, row["name"], row["company"]):
                pid = h.get("id")
                hit_li = (h.get("link") or {}).get("linkedin", "")
                st2, d2 = api.export_by_id(pid) if pid else (404, None)
                p = unwrap(d2) if st2 == 200 else None
                if p:
                    person, matched_by = p, "name_company"
                    linkedin = linkedin or hit_li
                    if not row["linkedin_url"] and hit_li:
                        row["linkedin_url"] = hit_li
                break

    if person:
        row["email"], row["email_confidence"] = pick_email(person)
        if not linkedin:
            linkedin = ((person.get("link") or {}).get("linkedin")) or ""

    if want_phone and (linkedin or (row["name"] and person)):
        domain = ""
        if isinstance(person, dict):
            comp = person.get("company") or {}
            domain = (comp.get("link") or {}).get("domain", "") if isinstance(comp, dict) else ""
            if not domain:
                for g in person.get("position_groups", []) or []:
                    domain = ((g.get("company") or {}).get("link") or {}).get("domain", "")
                    if domain:
                        break
        if linkedin:
            st, d = api.mobile_phone(linkedin=linkedin)
        elif domain:
            st, d = api.mobile_phone(name=row["name"], domain=domain)
        else:
            st, d = 404, None
        if st == 200 and isinstance(d, dict):
            nums = d.get("data") or []
            flat = [n for grp in nums for n in (grp if isinstance(grp, list) else [grp])]
            row["phone"] = flat[0] if flat else ""

    if row["email"] and row["phone"]:
        row["enrichment_status"] = f"email+phone ({matched_by})"
    elif row["email"]:
        row["enrichment_status"] = f"email_only ({matched_by})"
    elif row["phone"]:
        row["enrichment_status"] = f"phone_only ({matched_by or 'linkedin'})"
    elif not row["enrichment_status"]:
        row["enrichment_status"] = "not_found" if (row["linkedin_url"] or row["company"]) else "insufficient_input"
    return row


# ------------------------------------------------------------- step 3 + 4

FIELDS = ["name", "title", "company", "linkedin_url", "source_variant", "email", "email_confidence", "phone", "enrichment_status"]


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def summary(rows, per_file, api_calls, dry_run):
    print("\n=== Input files")
    for variant, name, n_in, n_kept, missing, cols in per_file:
        note = f"  (no column found for: {', '.join(missing)})" if missing else ""
        print(f"  [{variant}] {name}: {n_in} rows, {n_kept} new after dedupe{note}")
        print(f"       columns used: " + ", ".join(f"{k}<-'{v}'" for k, v in cols.items()))
    with_email = sum(1 for r in rows if r.get("email"))
    with_phone = sum(1 for r in rows if r.get("phone"))
    print("\n=== Summary")
    print(f"  total rows (after dedupe): {len(rows)}")
    print(f"  with linkedin_url:         {sum(1 for r in rows if r['linkedin_url'])}")
    if dry_run:
        print("  (dry run: no enrichment performed)")
    else:
        print(f"  with email:                {with_email}")
        print(f"  without email:             {len(rows) - with_email}")
        print(f"  with phone:                {with_phone}")
        print(f"  API calls this run:        {api_calls} (cached responses not counted)")
    print("\n  per source variant:")
    variants = sorted({v for r in rows for v in r["source_variant"].split("+")})
    for v in variants:
        sub = [r for r in rows if v in r["source_variant"].split("+")]
        e = sum(1 for r in sub if r.get("email"))
        print(f"    {v}: {len(sub)} rows, {e} with email, {len(sub) - e} without")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default="input", help="folder containing the exported CSVs (default ./input)")
    ap.add_argument("--out", default=str(OUT_FILE))
    ap.add_argument("--dry-run", action="store_true", help="merge and dedupe only; no API calls")
    ap.add_argument("--no-phone", action="store_true", help="skip the mobile phone finder (5 credits per hit)")
    ap.add_argument("--limit", type=int, default=0, help="enrich only the first N rows (for testing)")
    args = ap.parse_args()

    rows, per_file = merge(args.input)
    dry = args.dry_run or not API_KEY
    if not args.dry_run and not API_KEY:
        print("AIARK_API_KEY not set: running merge/dedupe only.", file=sys.stderr)

    api_calls = 0
    if not dry:
        api = AIArk(API_KEY)
        todo = rows[: args.limit] if args.limit else rows
        for i, r in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {r['name']} @ {r['company'] or '?'} ...", end=" ", flush=True)
            enrich_row(api, r, want_phone=not args.no_phone)
            print(r["enrichment_status"])
        for r in rows[len(todo):]:
            r.update({"email": "", "email_confidence": "", "phone": "", "enrichment_status": "skipped"})
        api_calls = api.calls
    else:
        for r in rows:
            r.update({"email": "", "email_confidence": "", "phone": "", "enrichment_status": "not_run"})

    write_csv(rows, args.out)
    summary(rows, per_file, api_calls, dry)
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
