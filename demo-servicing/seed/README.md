# Seed Data

Synthetic closing binder for the RolledCo demo. Every page carries the footer
"SAMPLE, SYNTHETIC DATA. Names, entities and figures are invented."

Regenerate with `python seed/make_seed.py`.

## The Deal

Northgate Acquisition LLC (buyer, owner Dana Whitfield) buys the assets of
Brightline Heating & Air LLC from Ray Kowalski for $2,400,000, closing
July 15, 2026.

| Source | Amount | Terms |
| --- | --- | --- |
| SBA 7(a) loan, Harbor Federal Bank | $1,920,000 | 10 years, Prime + 2.75% (10.25% at commitment), about $25,639 per month from August 15, 2026 |
| Buyer cash | $240,000 | Equity injection |
| Seller Note A | $120,000 | 6% simple, full standby for the life of the SBA loan, no payments while on standby, counts toward equity injection |
| Seller Note B | $120,000 | 6% accruing, 24 month standby then 36 monthly installments, principal reduced dollar for dollar below $3,100,000 trailing revenue at month 24, floor $60,000 |

Other post-close obligations: consulting agreement with the seller ($6,000 per
month for 12 months, 20 hours per month, customer introduction schedule);
retention bonuses for the service manager ($15,000), lead technician ($10,000)
and office manager ($8,000), each in three annual tranches on the anniversary
of close; a $50,000 holdback held by buyer's counsel, released at month six
once the net working capital true-up is settled; lender reporting (quarterly
financials within 45 days, annual tax returns within 120 days of year end).

## Binder (`binder/`)

| File | Document |
| --- | --- |
| 01_letter_of_intent.pdf | Signed letter of intent, April 2, 2026 |
| 02_asset_purchase_agreement_excerpt.pdf | Article II (price, payment, seller notes, NWC adjustment, holdback) plus signature page |
| 03_seller_note_a.pdf | Seller Note A, $120,000, full standby |
| 04_seller_note_b.pdf | Seller Note B, $120,000, performance note |
| 05_standby_creditor_agreement.pdf | Standby creditor's agreement modeled on the structure of SBA Form 155 |
| 06_consulting_agreement.pdf | Seller consulting agreement with customer introduction schedule |
| 07a_retention_bonus_service_manager.pdf | Luis Herrera, $15,000 |
| 07b_retention_bonus_lead_technician.pdf | Tasha Nguyen, $10,000 |
| 07c_retention_bonus_office_manager.pdf | Carol Dempsey, $8,000 |
| 08_lender_commitment_letter_excerpt.pdf | Harbor Federal Bank commitment, loan terms and reporting covenants |
| 09_closing_funds_flow.pdf | Sources and uses, closing costs, post-closing obligation summary |

## Problems Planted on Purpose

1. **Note B first payment date conflict.** Seller Note B, Section 4, says the
   first installment is due August 15, 2028. The asset purchase agreement,
   Section 2.4, says September 15, 2028.
2. **Missing forfeiture clause.** The office manager's retention bonus letter
   (07c) has no continued employment condition or forfeiture language. The
   other two letters do (their Section 3).

## Monthly P&L (`pnl/`)

Six CSV files, `pnl_2026-07.csv` through `pnl_2026-12.csv`, each a simple
line item statement (revenue by line, cost of sales, operating expenses,
interest, net income). These stand in for an accounting connection.

Revenue runs slightly under the Note B threshold:

| Month | Revenue |
| --- | --- |
| July 2026 | $262,400 |
| August 2026 | $268,900 |
| September 2026 | $258,100 |
| October 2026 | $246,800 |
| November 2026 | $241,100 |
| December 2026 | $250,200 |
| Six month total | $1,527,500 |
| Annualized | $3,055,000 against a $3,100,000 threshold |
