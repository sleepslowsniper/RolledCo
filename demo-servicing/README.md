# RolledCo Servicing Demo

A local, single-command demo of RolledCo as the servicing layer for post-close
money in a small business acquisition. It reads a synthetic closing binder,
builds one ledger of every payment the buyer owes after close, monitors
compliance, computes amounts from the books, and prepares instructions and
statements for a person to approve. RolledCo never holds or moves funds.

Everything in here is synthetic. It is a demo, not production.

## Run It

```bash
cd demo-servicing
pip install -r requirements.txt
./run.sh
```

Then open http://localhost:8000. The clock is frozen at January 15, 2027
(six months after close) so every screen tells the same story on every take.

Equivalent: `python app/server.py`. Set `PORT` to change the port.

## What Is Where

| Path | What |
| --- | --- |
| `seed/binder/` | Eleven closing documents as PDFs. Every page says SAMPLE, SYNTHETIC DATA. |
| `seed/pnl/` | Six monthly P&L CSVs, July to December 2026, standing in for an accounting connection. |
| `seed/make_seed.py` | Regenerates the binder and the CSVs. |
| `seed/README.md` | The deal, the file index, and the two problems planted on purpose. |
| `extract.py` | Runs each PDF through the Anthropic API and writes `data/obligations.json`. |
| `data/obligations.json` | The extraction the app reads. Ships as a cache so the demo is instant. |
| `data/obligations.cached.json` | The committed copy. Reset Demo restores it. |
| `data/state.json` | Review decisions and outbox approvals. Created on first use, deleted by Reset Demo. |
| `app/server.py` | FastAPI server and JSON API. |
| `app/ledger.py` | Ledger engine: schedules, totals, Note B month-end math, the standby check. |
| `app/static/` | The single-page UI. Vanilla JS, no build step. Fonts are vendored. |
| `DEMO_SCRIPT.md` | The seven-beat click path with spoken lines. |
| `ledger.png` | 1440 by 900 screenshot of the Ledger screen for the deck. |

## The Screens

1. **Closing Binder.** The eleven documents, with Extract Obligations. The
   progress view names each agent as it runs: Reader, Compliance, Calculation,
   Servicing. Extract replays the cached result. Re-run Extraction calls the API.
2. **Review.** One row per obligation with instrument, counterparty, amount,
   next date, confidence, View Source, and Approve, Edit, Reject. The two
   planted problems show as crimson flags: the Note B first payment date
   conflict, and the bonus letter with no forfeiture clause.
3. **Ledger.** Ten year timeline, one row per instrument, a marker per
   obligation, standby periods shaded. Totals for this month, the next twelve
   months, and outstanding by counterparty. Click any marker for the schedule.
4. **Monitor.** Schedule Payment on Seller Note A is blocked with the standby
   clause quoted. Run Month End reads the P&L CSVs and lays out the Note B
   revenue test line by line. Lender reporting due dates with status.
5. **Outbox.** Three drafts from the servicing agent: a payment instruction
   for this month's consulting fee, a seller statement, and a quarterly lender
   package cover note. Approve marks the instruction "Approved, ready for
   buyer's bank". Nothing is sent anywhere.

The **Seller View** toggle (top right) shows a read-only page with only what
the seller is owed and when.

**Reset Demo** (bottom of the nav) clears decisions and approvals and restores
the cached extraction, so each recording take starts clean.

## Live Extraction

The app works with no API key. To re-run extraction against the API:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export ANTHROPIC_MODEL=claude-opus-5-5   # optional, this is the default
./run.sh
```

Then click Re-run Extraction on the Closing Binder screen, or run
`python extract.py` directly. The script makes one structured-output call per
document (the Reader), one cross-document call for conflicts and missing terms
(Compliance), then computes dates locally (Calculation) and writes the file
(Servicing). It overwrites `data/obligations.json`; Reset Demo puts the cached
copy back.

## Constraints

Local only. No auth, no database, no deployment. The only external call is the
Anthropic API, and only when you click Re-run Extraction or run `extract.py`.
No email is sent. No funds are held or moved.

## Design

White background, ink #1A1A1A text, crimson #8B1A1A as the single accent,
off-white #F6F2EE panels. Barlow Condensed Bold for headings, Inter for body.
Laid out for 1440 by 900.
