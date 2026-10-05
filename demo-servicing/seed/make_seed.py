"""
Generates the synthetic closing binder for the RolledCo demo.

    python seed/make_seed.py

Writes:
    seed/binder/*.pdf   eleven closing documents
    seed/pnl/*.csv      six monthly P&L files, July to December 2026

Everything here is invented. Every page carries a SAMPLE, SYNTHETIC DATA footer.
Two problems are seeded on purpose so the extraction has something to catch:
  1. Seller Note B says the first installment is August 15, 2028. The asset
     purchase agreement says September 15, 2028.
  2. The office manager's retention bonus letter has no forfeiture clause.
"""
import csv
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

HERE = Path(__file__).parent
BINDER = HERE / "binder"
PNL = HERE / "pnl"
BINDER.mkdir(exist_ok=True)
PNL.mkdir(exist_ok=True)

FOOTER = "SAMPLE, SYNTHETIC DATA. Names, entities and figures are invented."

# ---------------------------------------------------------------- styles
BODY = ParagraphStyle("body", fontName="Times-Roman", fontSize=10.5, leading=14,
                      alignment=TA_JUSTIFY, spaceAfter=7)
BODY_L = ParagraphStyle("bodyl", parent=BODY, alignment=0)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=9, leading=11.5)
TITLE = ParagraphStyle("title", fontName="Times-Bold", fontSize=15, leading=19,
                       alignment=TA_CENTER, spaceAfter=4)
SUB = ParagraphStyle("sub", fontName="Times-Roman", fontSize=10.5, leading=14,
                     alignment=TA_CENTER, spaceAfter=14)
H = ParagraphStyle("h", fontName="Times-Bold", fontSize=11, leading=14,
                   spaceBefore=9, spaceAfter=4)
LETTERHEAD = ParagraphStyle("lh", fontName="Times-Bold", fontSize=13, leading=16)
LETTERHEAD_SUB = ParagraphStyle("lhs", fontName="Times-Roman", fontSize=9.5,
                                leading=12, spaceAfter=16)
RIGHT = ParagraphStyle("right", parent=BODY_L, alignment=2)


class NumberedCanvas(canvas.Canvas):
    """Adds 'Page X of Y' and the synthetic-data footer to every page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._footer(total)
            super().showPage()
        super().save()

    def _footer(self, total):
        self.saveState()
        self.setStrokeColor(colors.HexColor("#8B1A1A"))
        self.setLineWidth(0.6)
        self.line(inch, 0.78 * inch, letter[0] - inch, 0.78 * inch)
        self.setFont("Helvetica-Bold", 7.5)
        self.setFillColor(colors.HexColor("#8B1A1A"))
        self.drawString(inch, 0.6 * inch, FOOTER)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#1A1A1A"))
        self.drawRightString(letter[0] - inch, 0.6 * inch,
                             f"{self._doc_label}  |  Page {self._pageNumber} of {total}")
        self.restoreState()


def build(filename, label, story, title):
    path = BINDER / filename
    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=inch, rightMargin=inch,
                            topMargin=0.9 * inch, bottomMargin=1.05 * inch,
                            title=title, author="RolledCo demo seed")

    def make_canvas(*a, **k):
        c = NumberedCanvas(*a, **k)
        c._doc_label = label
        return c

    doc.build(story, canvasmaker=make_canvas)
    print("wrote", path.relative_to(HERE.parent))


def P(text, style=BODY):
    return Paragraph(text, style)


def sig_block(pairs):
    """pairs: list of (party heading, signer line, title line)."""
    rows = []
    for heading, signer, title in pairs:
        rows.append([P(f"<b>{heading}</b>", BODY_L), ""])
        rows.append([P(f"By: <u>/s/ {signer}</u>", BODY_L), ""])
        rows.append([P(f"Name: {signer}", BODY_L), ""])
        rows.append([P(f"Title: {title}", BODY_L), ""])
        rows.append([Spacer(1, 8), ""])
    t = Table(rows, colWidths=[4.2 * inch, 2.3 * inch])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def money(n):
    return f"${n:,.2f}" if isinstance(n, float) else f"${n:,}"


CELL = ParagraphStyle("cell", fontName="Times-Roman", fontSize=9.5, leading=12)
CELL_B = ParagraphStyle("cellb", parent=CELL, fontName="Times-Bold")
CELL_R = ParagraphStyle("cellr", parent=CELL, alignment=2)


def grid(data, widths, header=True, align_right_cols=()):
    rows = []
    for r, row in enumerate(data):
        cells = []
        for c, val in enumerate(row):
            if isinstance(val, str):
                style = CELL_B if (header and r == 0) else (CELL_R if c in align_right_cols else CELL)
                val = Paragraph(val, style)
            cells.append(val)
        rows.append(cells)
    t = Table(rows, colWidths=widths)
    style = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
             ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 3),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F6F2EE")))
    t.setStyle(TableStyle(style))
    return t


# ---------------------------------------------------------------- deal facts
BUYER = "Northgate Acquisition LLC"
BUYER_OWNER = "Dana Whitfield"
SELLER_CO = "Brightline Heating &amp; Air LLC"
SELLER = "Ray Kowalski"
BANK = "Harbor Federal Bank"
BANK_OFFICER = "Priya Raman"
BUYER_COUNSEL = "Ashcroft Lowe LLP"
SELLER_COUNSEL = "Marchetti Legal PLLC"
CLOSE = "July 15, 2026"
PRICE = 2_400_000
LOAN = 1_920_000
CASH = 240_000
NOTE_A = 120_000
NOTE_B = 120_000
HOLDBACK = 50_000
THRESHOLD = 3_100_000
FLOOR = 60_000


def sba_payment(principal=LOAN, annual_rate=0.1025, months=120):
    r = annual_rate / 12
    return principal * r * (1 + r) ** months / ((1 + r) ** months - 1)


SBA_PMT = round(sba_payment(), 2)

# ---------------------------------------------------------------- 01 LOI
def doc_loi():
    s = []
    s += [P(BUYER, LETTERHEAD), P("1400 Prairie Center Drive, Suite 210, Rockford, Illinois 61108", LETTERHEAD_SUB)]
    s += [P("April 2, 2026", BODY_L), Spacer(1, 6)]
    s += [P(f"Mr. {SELLER}<br/>{SELLER_CO}<br/>2210 Industrial Parkway<br/>Rockford, Illinois 61109", BODY_L), Spacer(1, 6)]
    s += [P("<b>Re: Letter of Intent to Acquire Substantially All Assets of Brightline Heating &amp; Air LLC</b>", BODY_L)]
    s += [P(f"Dear Ray,")]
    s += [P(f"This letter sets out the principal terms on which {BUYER} (\"Buyer\"), a company owned by {BUYER_OWNER}, proposes to acquire substantially all of the assets of {SELLER_CO} (the \"Company\") from you (\"Seller\"). Except for the paragraphs headed Exclusivity, Confidentiality and Expenses, this letter is non-binding and is intended only to guide the negotiation of a definitive asset purchase agreement.")]
    s += [P("<b>1. Purchase Price.</b> The total purchase price will be $2,400,000, subject to a customary net working capital adjustment against a target of $310,000, payable as follows:")]
    s += [grid([["Component", "Amount", "Terms"],
                ["Cash at closing", money(LOAN + CASH - HOLDBACK), "Funded from an SBA 7(a) loan and Buyer's cash equity"],
                ["Holdback", money(HOLDBACK), "Held by Buyer's counsel, released at month six upon settlement of the net working capital true-up"],
                ["Seller Note A", money(NOTE_A), "Full standby for the life of the SBA loan, 6% interest accruing, counts toward Buyer's equity injection"],
                ["Seller Note B", money(NOTE_B), "Performance note, two year standby then 36 monthly installments, principal adjusted to trailing revenue at month 24"],
                ["Total", money(PRICE), ""]],
               [1.3 * inch, 1.1 * inch, 4.1 * inch], align_right_cols=(1,))]
    s += [Spacer(1, 8)]
    s += [P("<b>2. Financing.</b> Buyer intends to finance the acquisition with an SBA 7(a) loan of approximately $1,920,000 from Harbor Federal Bank, cash equity of $240,000, and the two seller notes described above. Buyer's obligation to close will be conditioned on receipt of that financing on terms reasonably acceptable to Buyer.")]
    s += [P(f"<b>3. Transition.</b> Seller will enter into a consulting agreement for twelve months following closing at $6,000 per month for up to 20 hours per month, including a scheduled program of introductions to the Company's principal commercial customers.")]
    s += [P("<b>4. Key Employees.</b> Buyer intends to offer retention bonuses to the Company's service manager, lead technician and office manager, payable in three annual tranches on the anniversaries of closing, conditioned on continued employment.")]
    s += [P("<b>5. Target Closing.</b> The parties will work toward a closing on or about July 15, 2026.")]
    s += [P("<b>6. Exclusivity.</b> For 75 days from the date Seller countersigns this letter, Seller will not solicit or negotiate any offer for the Company or its assets from any other party.")]
    s += [P("<b>7. Confidentiality.</b> The terms of this letter and all information exchanged in diligence are confidential and subject to the mutual non-disclosure agreement dated February 11, 2026.")]
    s += [P("<b>8. Expenses.</b> Each party will bear its own costs, except that Buyer will pay the SBA guarantee fee and the lender's closing costs.")]
    s += [P("If these terms are acceptable, please countersign below.")]
    s += [Spacer(1, 8), P("Sincerely,", BODY_L), Spacer(1, 4)]
    s += [sig_block([(BUYER, BUYER_OWNER, "Managing Member")])]
    s += [P("Accepted and agreed as of April 6, 2026:", BODY_L), Spacer(1, 4)]
    s += [sig_block([(SELLER_CO, SELLER, "Sole Member")])]
    build("01_letter_of_intent.pdf", "Letter of Intent", s, "Letter of Intent")


# ---------------------------------------------------------------- 02 APA excerpt
def doc_apa():
    s = []
    s += [P("ASSET PURCHASE AGREEMENT", TITLE),
          P(f"by and among {BUYER}, as Buyer, {SELLER_CO}, as Seller, and {SELLER}, as Owner<br/>Dated as of {CLOSE}", SUB)]
    s += [P("<i>Excerpt. Article II (Purchase Price and Payment) and Section 2.6 (Holdback) are reproduced in full. Other articles are omitted from this binder copy.</i>", SMALL)]
    s += [P("ARTICLE II<br/>PURCHASE PRICE AND PAYMENT", H)]
    s += [P("<b>Section 2.1 Purchase Price.</b> The aggregate consideration for the Purchased Assets (the \"Purchase Price\") is Two Million Four Hundred Thousand Dollars ($2,400,000), subject to adjustment under Section 2.5, and shall be paid as set out in Section 2.2.")]
    s += [P("<b>Section 2.2 Payment at Closing.</b> At the Closing, Buyer shall pay or deliver the Purchase Price as follows:")]
    s += [P("(a) Two Million One Hundred Ten Thousand Dollars ($2,110,000) in immediately available funds by wire transfer to the account designated by Seller;", BODY_L)]
    s += [P("(b) Fifty Thousand Dollars ($50,000) (the \"Holdback Amount\") by wire transfer to Ashcroft Lowe LLP, as holdback agent, to be held and released in accordance with Section 2.6;", BODY_L)]
    s += [P("(c) a promissory note in the original principal amount of One Hundred Twenty Thousand Dollars ($120,000) in the form of Exhibit B-1 (\"Seller Note A\"); and", BODY_L)]
    s += [P("(d) a promissory note in the original principal amount of One Hundred Twenty Thousand Dollars ($120,000) in the form of Exhibit B-2 (\"Seller Note B\").", BODY_L)]
    s += [P("<b>Section 2.3 Seller Note A.</b> Seller Note A shall bear simple interest at six percent (6%) per annum, shall be subordinated to the SBA Loan on a full standby basis for the life of the SBA Loan pursuant to the Standby Creditor's Agreement, and no payment of principal or interest shall be made on Seller Note A while any amount remains outstanding under the SBA Loan. Buyer and Seller acknowledge that Seller Note A is intended to be counted toward Buyer's equity injection under the SBA Loan.")]
    s += [P("<b>Section 2.4 Seller Note B.</b> Seller Note B shall bear simple interest at six percent (6%) per annum, shall be subject to a standby period of twenty-four (24) months following the Closing Date during which no payments shall be made, and thereafter shall be payable in thirty-six (36) equal consecutive monthly installments of principal and interest, the first such installment being due on <b>September 15, 2028</b> and continuing on the fifteenth day of each month thereafter. The principal amount of Seller Note B shall be adjusted as provided in Section 2.4(a).")]
    s += [P("(a) <i>Performance Adjustment.</i> If Trailing Twelve Month Revenue of the Business measured as of the last day of the twenty-fourth (24th) full calendar month following the Closing Date (the \"Measurement Date\") is less than Three Million One Hundred Thousand Dollars ($3,100,000) (the \"Revenue Threshold\"), the principal amount of Seller Note B shall be reduced, dollar for dollar, by the amount of the shortfall, provided that in no event shall the principal amount of Seller Note B be reduced below Sixty Thousand Dollars ($60,000). Buyer shall deliver its calculation of Trailing Twelve Month Revenue to Seller within thirty (30) days after the Measurement Date, and Seller shall have thirty (30) days to object.", BODY_L)]
    s += [P("<b>Section 2.5 Net Working Capital Adjustment.</b> The Purchase Price shall be increased or decreased, dollar for dollar, by the amount by which Closing Net Working Capital exceeds or is less than the Target Net Working Capital of Three Hundred Ten Thousand Dollars ($310,000). Buyer shall deliver a closing statement within ninety (90) days after the Closing Date. Any amount owed to Seller shall be paid within ten (10) business days after the closing statement becomes final; any amount owed to Buyer shall be satisfied first from the Holdback Amount.")]
    s += [P("<b>Section 2.6 Holdback.</b> The Holdback Amount shall be held by Ashcroft Lowe LLP in a non-interest-bearing client trust account. On the date that is six (6) months after the Closing Date, the holdback agent shall release the Holdback Amount, less any amount applied under Section 2.5 and less any pending indemnification claim under Article VIII, to Seller, provided that the net working capital adjustment under Section 2.5 has been finally settled. If the adjustment has not been finally settled on that date, release shall occur within five (5) business days after final settlement.")]
    s += [P("<b>Section 2.7 Allocation.</b> The Purchase Price shall be allocated among the Purchased Assets in accordance with Section 1060 of the Code and the allocation schedule attached as Schedule 2.7.")]
    s += [P("<b>Section 2.8 Transfer Taxes.</b> Seller shall bear all sales, use and transfer taxes arising from the transfer of the Purchased Assets.")]
    s += [Spacer(1, 10), P("[Remainder of Article II intentionally omitted from binder excerpt]", SMALL)]
    s += [PageBreak(), P("SIGNATURE PAGE TO ASSET PURCHASE AGREEMENT", H)]
    s += [sig_block([(f"BUYER: {BUYER}", BUYER_OWNER, "Managing Member"),
                     (f"SELLER: {SELLER_CO}", SELLER, "Sole Member"),
                     ("OWNER:", SELLER, "Individually")])]
    build("02_asset_purchase_agreement_excerpt.pdf", "Asset Purchase Agreement (Excerpt)", s,
          "Asset Purchase Agreement Excerpt")


# ---------------------------------------------------------------- 03 Note A
def doc_note_a():
    s = []
    s += [P("SUBORDINATED PROMISSORY NOTE", TITLE), P("(Seller Note A)", SUB)]
    s += [grid([["Principal Amount:", money(NOTE_A)], ["Date:", CLOSE], ["Place:", "Rockford, Illinois"]],
               [1.6 * inch, 4.9 * inch], header=False)]
    s += [Spacer(1, 10)]
    s += [P(f"FOR VALUE RECEIVED, {BUYER}, an Illinois limited liability company (\"Maker\"), promises to pay to the order of {SELLER}, an individual (\"Holder\"), the principal sum of One Hundred Twenty Thousand Dollars ($120,000), together with interest as provided below.")]
    s += [P("<b>1. Interest.</b> Interest shall accrue on the unpaid principal balance at the rate of six percent (6%) per annum, computed as simple interest on the basis of a 365-day year, from the date of this Note until paid in full.")]
    s += [P("<b>2. Standby; No Payments.</b> This Note is subject to a full standby for the life of the loan made by Harbor Federal Bank to Maker on or about the date of this Note under the U.S. Small Business Administration 7(a) loan program (the \"SBA Loan\"). <b>No payment of principal or interest shall be made or accepted under this Note so long as any amount remains outstanding under the SBA Loan</b>, unless Harbor Federal Bank and the SBA have given prior written consent. Interest shall continue to accrue during the standby period and shall be added to the amount due at maturity.")]
    s += [P("<b>3. Maturity.</b> All unpaid principal and accrued interest shall be due and payable in a single payment on the date that is thirty (30) days after the SBA Loan has been paid in full, and in any event not earlier than July 15, 2036 (the \"Maturity Date\"). Based on the ten-year term of the SBA Loan, the parties expect the Maturity Date to be August 14, 2036.")]
    s += [P("<b>4. Equity Injection.</b> Maker and Holder acknowledge that this Note is intended to be counted toward Maker's equity injection for the SBA Loan and that it has been placed on full standby for that purpose under a Standby Creditor's Agreement of even date in favor of Harbor Federal Bank.")]
    s += [P("<b>5. Prepayment.</b> Maker may not prepay this Note while the SBA Loan is outstanding without the prior written consent of Harbor Federal Bank. After the SBA Loan is paid in full, Maker may prepay without premium or penalty.")]
    s += [P("<b>6. Default.</b> Failure to pay any amount within ten (10) days after the Maturity Date shall constitute an event of default, after which the unpaid balance shall bear interest at nine percent (9%) per annum.")]
    s += [P("<b>7. Subordination.</b> This Note and all rights of Holder are subordinate to the SBA Loan and the related security interests in all respects, and Holder shall take no action to collect on this Note that is inconsistent with the Standby Creditor's Agreement.")]
    s += [P("<b>8. Governing Law.</b> This Note is governed by the laws of the State of Illinois.")]
    s += [Spacer(1, 12), sig_block([(f"MAKER: {BUYER}", BUYER_OWNER, "Managing Member")])]
    s += [P("Acknowledged by Holder:", BODY_L), sig_block([("HOLDER:", SELLER, "Individually")])]
    build("03_seller_note_a.pdf", "Seller Note A", s, "Seller Note A")


# ---------------------------------------------------------------- 04 Note B
def doc_note_b():
    s = []
    s += [P("SUBORDINATED PERFORMANCE PROMISSORY NOTE", TITLE), P("(Seller Note B)", SUB)]
    s += [grid([["Original Principal Amount:", money(NOTE_B)], ["Date:", CLOSE], ["Place:", "Rockford, Illinois"]],
               [2.0 * inch, 4.5 * inch], header=False)]
    s += [Spacer(1, 10)]
    s += [P(f"FOR VALUE RECEIVED, {BUYER}, an Illinois limited liability company (\"Maker\"), promises to pay to the order of {SELLER}, an individual (\"Holder\"), the Adjusted Principal Amount (defined below), together with interest as provided below.")]
    s += [P("<b>1. Interest.</b> Interest shall accrue at the rate of six percent (6%) per annum, computed as simple interest, from the date of this Note. Interest that accrues during the Standby Period shall not be paid currently; it shall be added to the Adjusted Principal Amount at the end of the Standby Period and amortized with it. Upon determination of the Adjusted Principal Amount, interest accrued during the Standby Period shall be recomputed on the Adjusted Principal Amount from the date of this Note.")]
    s += [P("<b>2. Standby Period.</b> No payment of principal or interest shall be made during the twenty-four (24) months following the date of this Note (the \"Standby Period\"). The Standby Period ends on July 15, 2028.")]
    s += [P("<b>3. Performance Adjustment.</b> If Trailing Twelve Month Revenue of the business acquired by Maker, measured as of the last day of the twenty-fourth (24th) full calendar month after the date of this Note (the \"Measurement Date\"), is less than Three Million One Hundred Thousand Dollars ($3,100,000) (the \"Revenue Threshold\"), then the principal amount of this Note shall be reduced, dollar for dollar, by the amount by which Trailing Twelve Month Revenue is less than the Revenue Threshold; provided, however, that the principal amount shall in no event be reduced below Sixty Thousand Dollars ($60,000) (the \"Floor\"). The principal amount as so adjusted is the \"Adjusted Principal Amount\". If Trailing Twelve Month Revenue equals or exceeds the Revenue Threshold, the Adjusted Principal Amount shall be the Original Principal Amount. \"Trailing Twelve Month Revenue\" means gross revenue of the business for the twelve full calendar months ending on the Measurement Date, determined in accordance with GAAP consistently applied, excluding revenue from any business acquired by Maker after the date of this Note.")]
    s += [P("<b>4. Repayment.</b> Following the Standby Period, the Adjusted Principal Amount plus interest accrued during the Standby Period shall be repaid in thirty-six (36) equal consecutive monthly installments of principal and interest, amortized at six percent (6%) per annum. <b>The first installment shall be due on August 15, 2028</b>, and subsequent installments shall be due on the fifteenth (15th) day of each calendar month thereafter, with the final installment due on July 15, 2031.")]
    s += [P("<b>5. Subordination.</b> This Note is subordinate to the loan made by Harbor Federal Bank to Maker under the SBA 7(a) program and is subject to the Standby Creditor's Agreement of even date. Payments under Section 4 are permitted only to the extent allowed by that agreement and so long as no default exists under the SBA Loan.")]
    s += [P("<b>6. Prepayment.</b> After the Standby Period, Maker may prepay this Note in whole or in part without premium or penalty, subject to the consent of Harbor Federal Bank if then required.")]
    s += [P("<b>7. Default.</b> Failure to pay any installment within ten (10) days after its due date shall constitute an event of default, after which Holder may, subject to Section 5, declare the unpaid balance immediately due.")]
    s += [P("<b>8. Governing Law.</b> This Note is governed by the laws of the State of Illinois.")]
    s += [Spacer(1, 12), sig_block([(f"MAKER: {BUYER}", BUYER_OWNER, "Managing Member")])]
    s += [P("Acknowledged by Holder:", BODY_L), sig_block([("HOLDER:", SELLER, "Individually")])]
    build("04_seller_note_b.pdf", "Seller Note B", s, "Seller Note B")


# ---------------------------------------------------------------- 05 standby creditor agreement
def doc_standby():
    s = []
    s += [P("STANDBY CREDITOR'S AGREEMENT", TITLE),
          P("Modeled on the structure of SBA Form 155. This is a synthetic document, not an SBA form.", SUB)]
    s += [grid([["SBA Loan Number:", "PLP 7A-2026-184-0931 (synthetic)"],
                ["Lender:", f"{BANK}, 400 Harbor Street, Chicago, Illinois 60606"],
                ["Borrower:", f"{BUYER}, 1400 Prairie Center Drive, Suite 210, Rockford, Illinois 61108"],
                ["Standby Creditor:", f"{SELLER}, 118 Birchwood Lane, Rockford, Illinois 61107"],
                ["Standby Loans:", "Seller Note A, $120,000, dated July 15, 2026; Seller Note B, $120,000, dated July 15, 2026"],
                ["Amount of SBA Loan:", money(LOAN)]],
               [1.6 * inch, 4.9 * inch], header=False)]
    s += [Spacer(1, 10)]
    s += [P("<b>1. Standby.</b> In consideration of Lender making the SBA Loan to Borrower, Standby Creditor agrees that the Standby Loans are subordinated to the SBA Loan and that Standby Creditor will not accept, and Borrower will not make, any payment of principal or interest on the Standby Loans except as expressly permitted in Section 2, until the SBA Loan has been paid in full.")]
    s += [P("<b>2. Permitted Payments.</b>")]
    s += [P("(a) <i>Seller Note A.</i> Full standby. No payments of principal or interest are permitted for the life of the SBA Loan. Interest may accrue.", BODY_L)]
    s += [P("(b) <i>Seller Note B.</i> No payments of principal or interest are permitted during the twenty-four (24) months following the date of this Agreement. Thereafter, Borrower may make the regularly scheduled monthly installments of principal and interest provided in Seller Note B, provided that no payment shall be made at any time when (i) Borrower is in default under the SBA Loan, (ii) Lender has given Borrower written notice that a payment would cause a default, or (iii) Borrower's debt service coverage ratio, measured on a trailing twelve month basis, is below 1.15 to 1.00.", BODY_L)]
    s += [P("<b>3. No Enforcement.</b> Standby Creditor will not demand, sue for, accelerate, or take any security for the Standby Loans, and will not commence or join any bankruptcy or similar proceeding against Borrower, while any part of the SBA Loan is outstanding, without Lender's prior written consent.")]
    s += [P("<b>4. Payments Received in Error.</b> Any payment received by Standby Creditor in violation of this Agreement shall be held in trust for Lender and promptly turned over to Lender for application to the SBA Loan.")]
    s += [P("<b>5. Equity Injection.</b> Standby Creditor acknowledges that Seller Note A is being counted as part of Borrower's equity injection for the SBA Loan and agrees that Seller Note A will remain on full standby for the life of the SBA Loan.")]
    s += [P("<b>6. Legend.</b> Standby Creditor shall mark each Standby Loan instrument with a legend stating that it is subject to this Agreement, and shall deliver the originals to Lender for retention until the SBA Loan is paid in full.")]
    s += [P("<b>7. Modification.</b> Neither the Standby Loans nor this Agreement may be modified without Lender's prior written consent.")]
    s += [P("<b>8. Term.</b> This Agreement remains in effect until the SBA Loan is paid in full and Lender has no further commitment to lend.")]
    s += [Spacer(1, 12), sig_block([("STANDBY CREDITOR:", SELLER, "Individually"),
                                    (f"BORROWER: {BUYER}", BUYER_OWNER, "Managing Member"),
                                    (f"LENDER: {BANK}", BANK_OFFICER, "Vice President, SBA Lending")])]
    build("05_standby_creditor_agreement.pdf", "Standby Creditor's Agreement", s, "Standby Creditor's Agreement")


# ---------------------------------------------------------------- 06 consulting agreement
def doc_consulting():
    s = []
    s += [P("CONSULTING AGREEMENT", TITLE), P(f"between {BUYER} and {SELLER}<br/>Dated as of {CLOSE}", SUB)]
    s += [P(f"This Consulting Agreement (the \"Agreement\") is entered into as of {CLOSE} between {BUYER} (the \"Company\") and {SELLER} (\"Consultant\"), in connection with the Company's acquisition of the assets of Brightline Heating &amp; Air LLC.")]
    s += [P("<b>1. Services.</b> Consultant will provide transition services to the Company, including customer and vendor introductions, technical and operational knowledge transfer, assistance with pending bids, and such other services as the Company may reasonably request (the \"Services\").")]
    s += [P("<b>2. Term.</b> The term of this Agreement begins on the Closing Date and ends twelve (12) months later, on July 14, 2027, unless earlier terminated under Section 7.")]
    s += [P("<b>3. Time Commitment.</b> Consultant will make himself available for up to twenty (20) hours per month. Hours beyond twenty in any month require the Company's prior written approval and are compensated at $125 per hour.")]
    s += [P("<b>4. Compensation.</b> The Company will pay Consultant a fee of Six Thousand Dollars ($6,000) per month for each month of the term, payable in arrears on the last business day of each calendar month, beginning with the month ending August 31, 2026 and ending with the month ending July 31, 2027. The fee for the partial month of July 2026 is waived. The Company will reimburse pre-approved out-of-pocket expenses within thirty (30) days of invoice.")]
    s += [P("<b>5. Customer Introduction Schedule.</b> Consultant will arrange and attend in-person introductions with the following customers no later than the target dates shown. The Company will confirm each introduction in writing.")]
    s += [grid([["Customer", "Contact", "Annual revenue (approx.)", "Target date"],
                ["Prairie Ridge Senior Living", "Facilities Director", "$186,000", "August 31, 2026"],
                ["Rockford Public Schools, Dist. 205 (maintenance)", "Director of Operations", "$241,000", "August 31, 2026"],
                ["Kessler Property Group", "Portfolio Manager", "$158,000", "September 30, 2026"],
                ["Winnebago Medical Plaza", "Building Engineer", "$97,000", "September 30, 2026"],
                ["Harvest Table Restaurants (4 locations)", "Owner", "$74,000", "October 31, 2026"],
                ["Northern Illinois Cold Storage", "Plant Manager", "$132,000", "November 30, 2026"],
                ["St. Anselm Parish and School", "Business Manager", "$41,000", "December 31, 2026"],
                ["Fulton Street Lofts HOA", "Board President", "$38,000", "January 31, 2027"]],
               [2.4 * inch, 1.5 * inch, 1.5 * inch, 1.1 * inch], align_right_cols=(2,))]
    s += [Spacer(1, 8)]
    s += [P("<b>6. Independent Contractor.</b> Consultant is an independent contractor and not an employee. Consultant is responsible for his own taxes and is not eligible for Company benefits.")]
    s += [P("<b>7. Termination.</b> The Company may terminate this Agreement for Cause on written notice. Either party may terminate for the other's uncured material breach on thirty (30) days' notice. On termination, the Company's only obligation is to pay fees earned through the termination date. This Agreement does not affect Consultant's rights under Seller Note A or Seller Note B.")]
    s += [P("<b>8. Confidentiality and Non-Solicitation.</b> Consultant will keep Company information confidential and, during the term and for the restricted period under the Asset Purchase Agreement, will not solicit the Company's customers or employees.")]
    s += [P("<b>9. Governing Law.</b> Illinois.")]
    s += [Spacer(1, 12), sig_block([(f"COMPANY: {BUYER}", BUYER_OWNER, "Managing Member"),
                                    ("CONSULTANT:", SELLER, "Individually")])]
    build("06_consulting_agreement.pdf", "Consulting Agreement", s, "Consulting Agreement")


# ---------------------------------------------------------------- 07 retention bonus letters
EMPLOYEES = [
    ("07a_retention_bonus_service_manager.pdf", "Luis Herrera", "Service Manager", 15_000, True),
    ("07b_retention_bonus_lead_technician.pdf", "Tasha Nguyen", "Lead Technician", 10_000, True),
    ("07c_retention_bonus_office_manager.pdf", "Carol Dempsey", "Office Manager", 8_000, False),
]


def tranches(total):
    base = round(total / 3, 2)
    return [base, base, round(total - 2 * base, 2)]


def doc_bonus(filename, name, title, total, include_forfeiture):
    t = tranches(total)
    s = []
    s += [P(BUYER, LETTERHEAD), P("1400 Prairie Center Drive, Suite 210, Rockford, Illinois 61108", LETTERHEAD_SUB)]
    s += [P(CLOSE, BODY_L), Spacer(1, 6)]
    s += [P(f"{name}<br/>c/o Brightline Heating &amp; Air<br/>2210 Industrial Parkway<br/>Rockford, Illinois 61109", BODY_L), Spacer(1, 6)]
    s += [P(f"<b>Re: Retention Bonus</b>", BODY_L)]
    s += [P(f"Dear {name.split()[0]},")]
    s += [P(f"As you know, {BUYER} has today acquired the business of Brightline Heating &amp; Air. Your role as {title} is important to the continued success of the business, and we want to recognize that. This letter confirms the retention bonus we discussed.")]
    s += [P(f"<b>1. Bonus Amount.</b> You will be eligible for a total retention bonus of {money(total)} (the \"Retention Bonus\"), paid in three tranches on the anniversaries of the closing:")]
    s += [grid([["Tranche", "Payment date", "Amount"],
                ["First", "July 15, 2027", money(t[0])],
                ["Second", "July 15, 2028", money(t[1])],
                ["Third", "July 15, 2029", money(t[2])],
                ["Total", "", money(float(total))]],
               [1.2 * inch, 1.8 * inch, 1.4 * inch], align_right_cols=(2,))]
    s += [Spacer(1, 8)]
    s += [P("<b>2. Payment.</b> Each tranche will be paid through payroll, less applicable withholdings, on the next regular payroll date on or after the payment date shown above.")]
    if include_forfeiture:
        s += [P("<b>3. Condition of Continued Employment.</b> Each tranche is earned only if you remain continuously employed by the Company through the applicable payment date. If your employment ends for any reason before a payment date, whether by resignation or termination, with or without cause, any unpaid tranche is forfeited and no pro-rated amount is owed.")]
        s += [P("<b>4. Not a Contract of Employment.</b> Your employment remains at will. Nothing in this letter guarantees employment for any period.")]
        s += [P("<b>5. Entire Agreement.</b> This letter is the complete agreement regarding the Retention Bonus and supersedes any prior discussion. It may be amended only in a writing signed by both of us.")]
    else:
        # Seeded problem: no forfeiture or continued-employment condition.
        s += [P("<b>3. Not a Contract of Employment.</b> Your employment remains at will. Nothing in this letter guarantees employment for any period.")]
        s += [P("<b>4. Entire Agreement.</b> This letter is the complete agreement regarding the Retention Bonus and supersedes any prior discussion. It may be amended only in a writing signed by both of us.")]
    s += [P("We are glad to have you on the team. Please sign below to acknowledge.")]
    s += [Spacer(1, 8), P("Sincerely,", BODY_L), Spacer(1, 4)]
    s += [sig_block([(BUYER, BUYER_OWNER, "Managing Member")])]
    s += [P("Acknowledged and agreed:", BODY_L), sig_block([("EMPLOYEE:", name, title)])]
    build(filename, f"Retention Bonus, {title}", s, f"Retention Bonus Letter, {name}")


# ---------------------------------------------------------------- 08 lender commitment
def doc_lender():
    s = []
    s += [P(BANK, LETTERHEAD), P("SBA Lending Division, 400 Harbor Street, Chicago, Illinois 60606", LETTERHEAD_SUB)]
    s += [P("June 18, 2026", BODY_L), Spacer(1, 6)]
    s += [P(f"{BUYER_OWNER}, Managing Member<br/>{BUYER}<br/>1400 Prairie Center Drive, Suite 210<br/>Rockford, Illinois 61108", BODY_L), Spacer(1, 6)]
    s += [P("<b>Re: Commitment Letter, SBA 7(a) Term Loan, $1,920,000</b>", BODY_L)]
    s += [P("<i>Excerpt. Sections 1 (Loan Terms), 6 (Reporting Covenants) and 7 (Financial Covenants) are reproduced. Other sections are omitted from this binder copy.</i>", SMALL)]
    s += [P("Dear Ms. Whitfield,")]
    s += [P(f"{BANK} (\"Lender\") is pleased to commit to make a term loan to {BUYER} (\"Borrower\") under the U.S. Small Business Administration 7(a) guaranteed loan program on the terms below. This commitment is subject to SBA authorization and the conditions in Sections 2 through 5.")]
    s += [P("<b>1. Loan Terms.</b>")]
    s += [grid([["Loan amount", money(LOAN)],
                ["Purpose", f"Acquisition of substantially all assets of Brightline Heating &amp; Air LLC for a purchase price of {money(PRICE)}"],
                ["Term", "Ten (10) years from the date of the note, fully amortizing"],
                ["Interest rate", "Variable, Wall Street Journal Prime plus 2.75%, adjusted quarterly (10.25% at commitment)"],
                ["Estimated monthly payment", f"{money(SBA_PMT)} principal and interest at the commitment rate, due on the 15th of each month beginning August 15, 2026"],
                ["Equity injection", f"{money(CASH + NOTE_A)} (10% cash from Borrower, {money(CASH)}, and Seller Note A, {money(NOTE_A)}, on full standby)"],
                ["Seller financing", f"Seller Note B, {money(NOTE_B)}, subordinated with a 24 month standby under a Standby Creditor's Agreement"],
                ["Collateral", "First lien on all business assets of Borrower; personal guaranty of Dana Whitfield; life insurance assignment of $1,000,000"],
                ["SBA guarantee fee", "Per SBA schedule, payable at closing"]],
               [1.7 * inch, 4.8 * inch], header=False)]
    s += [Spacer(1, 8)]
    s += [P("<b>6. Reporting Covenants.</b> So long as any amount is outstanding under the loan, Borrower shall deliver to Lender:")]
    s += [P("(a) within forty-five (45) days after the end of each fiscal quarter, internally prepared financial statements of Borrower for that quarter and year to date, including a balance sheet, income statement and accounts receivable aging, certified by Borrower's managing member;", BODY_L)]
    s += [P("(b) within one hundred twenty (120) days after the end of each fiscal year, complete copies of Borrower's federal income tax returns for that year, including all schedules, together with a signed IRS Form 4506-C;", BODY_L)]
    s += [P("(c) within thirty (30) days after filing, copies of personal federal income tax returns of each guarantor; and", BODY_L)]
    s += [P("(d) promptly, notice of any litigation, material adverse change, or default under any seller financing.", BODY_L)]
    s += [P("Borrower's fiscal year ends December 31. The first quarterly report will cover the period from closing through September 30, 2026 and is due November 14, 2026.")]
    s += [P("<b>7. Financial Covenants.</b> Borrower shall maintain a debt service coverage ratio of not less than 1.25 to 1.00, measured annually on a trailing twelve month basis beginning with the fiscal year ending December 31, 2027. Borrower shall make no payment on any seller note while in default under the loan, and no payment on Seller Note A while the loan is outstanding.")]
    s += [P("This commitment expires if the loan has not closed by August 31, 2026. Please countersign to accept.")]
    s += [Spacer(1, 8), P("Sincerely,", BODY_L), Spacer(1, 4)]
    s += [sig_block([(BANK, BANK_OFFICER, "Vice President, SBA Lending")])]
    s += [P("Accepted June 22, 2026:", BODY_L), sig_block([(BUYER, BUYER_OWNER, "Managing Member")])]
    build("08_lender_commitment_letter_excerpt.pdf", "Lender Commitment Letter (Excerpt)", s,
          "Lender Commitment Letter Excerpt")


# ---------------------------------------------------------------- 09 funds flow
def doc_funds_flow():
    s = []
    s += [P("CLOSING FUNDS FLOW MEMORANDUM", TITLE),
          P(f"Acquisition of the assets of {SELLER_CO} by {BUYER}<br/>Closing Date: {CLOSE}<br/>Prepared by {BUYER_COUNSEL}, counsel to Buyer", SUB)]
    s += [P("SOURCES", H)]
    s += [grid([["Source", "Provider", "Amount", "Form"],
                ["SBA 7(a) term loan", BANK, money(LOAN), "Wire to closing account"],
                ["Buyer cash equity", f"{BUYER} ({BUYER_OWNER})", money(CASH), "Wire to closing account"],
                ["Seller Note A", f"{SELLER}", money(NOTE_A), "Non-cash, delivered at closing"],
                ["Seller Note B", f"{SELLER}", money(NOTE_B), "Non-cash, delivered at closing"],
                ["Total sources", "", money(PRICE), ""]],
               [1.6 * inch, 2.1 * inch, 1.1 * inch, 1.7 * inch], align_right_cols=(2,))]
    s += [P("USES", H)]
    s += [grid([["Use", "Payee", "Amount", "Form"],
                ["Cash purchase price paid at closing (APA Section 2.2(a))", f"{SELLER_CO}", money(LOAN + CASH - HOLDBACK), "Wire"],
                ["Holdback (APA Section 2.6)", f"{BUYER_COUNSEL}, holdback agent", money(HOLDBACK), "Wire to client trust account"],
                ["Seller Note A (APA Section 2.2(c))", SELLER, money(NOTE_A), "Note delivered"],
                ["Seller Note B (APA Section 2.2(d))", SELLER, money(NOTE_B), "Note delivered"],
                ["Total uses", "", money(PRICE), ""]],
               [2.3 * inch, 1.9 * inch, 1.1 * inch, 1.2 * inch], align_right_cols=(2,))]
    s += [P("BUYER CLOSING COSTS (PAID OUTSIDE THE PURCHASE PRICE)", H)]
    s += [grid([["Item", "Payee", "Amount"],
                ["SBA guarantee fee", "SBA via Lender", "$54,900.00"],
                ["Lender packaging and closing fee", BANK, "$4,500.00"],
                ["Buyer legal fees", BUYER_COUNSEL, "$18,750.00"],
                ["Quality of earnings review", "Keller &amp; Vance CPAs", "$12,000.00"],
                ["Lien searches, filings, title", "Various", "$1,340.00"],
                ["Total closing costs", "", "$91,490.00"]],
               [2.6 * inch, 2.4 * inch, 1.5 * inch], align_right_cols=(2,))]
    s += [P("POST-CLOSING PAYMENT OBLIGATIONS OF BUYER (SUMMARY FOR SERVICING)", H)]
    s += [grid([["Obligation", "Counterparty", "Terms"],
                ["SBA 7(a) loan", BANK, f"{money(SBA_PMT)} monthly, 15th of each month from August 15, 2026, 120 payments, variable rate"],
                ["Seller Note A", SELLER, "$120,000 at 6% simple, full standby, no payments while SBA loan outstanding"],
                ["Seller Note B", SELLER, "$120,000 at 6%, 24 month standby, 36 monthly installments, revenue adjustment at month 24"],
                ["Consulting fee", SELLER, "$6,000 per month, 12 months, paid last business day of month, August 2026 to July 2027"],
                ["Retention bonuses", "L. Herrera, T. Nguyen, C. Dempsey", "$33,000 total in three annual tranches, July 15, 2027, 2028 and 2029"],
                ["Holdback release", f"{SELLER} via {BUYER_COUNSEL}", "$50,000 released January 15, 2027 if NWC true-up settled"],
                ["Lender reporting", BANK, "Quarterly financials within 45 days, tax returns within 120 days of year end"]],
               [1.4 * inch, 1.7 * inch, 3.4 * inch])]
    s += [Spacer(1, 10)]
    s += [P("Wire confirmations for the closing account were received from Harbor Federal Bank (ref. HFB-0715-2241) and from Northgate Acquisition LLC (ref. NGA-0715-0018) at 10:42 a.m. and 9:15 a.m. Central time on the Closing Date. Disbursements were released at 1:05 p.m. Central time.", SMALL)]
    s += [Spacer(1, 8), sig_block([(f"Prepared by {BUYER_COUNSEL}", "Miriam Ashcroft", "Partner")])]
    build("09_closing_funds_flow.pdf", "Closing Funds Flow", s, "Closing Funds Flow")


# ---------------------------------------------------------------- P&L CSVs
# Revenue runs slightly under the Note B threshold: six-month total $1,527,500,
# which annualizes to $3,055,000 against a $3,100,000 threshold.
PNL_MONTHS = [
    ("2026-07", 262_400, (171_200, 68_400, 22_800)),
    ("2026-08", 268_900, (176_900, 69_100, 22_900)),
    ("2026-09", 258_100, (164_300, 70_600, 23_200)),
    ("2026-10", 246_800, (152_900, 70_400, 23_500)),
    ("2026-11", 241_100, (147_600, 69_900, 23_600)),
    ("2026-12", 250_200, (154_700, 71_700, 23_800)),
]


def write_pnl():
    for month, revenue, (service, install, plans) in PNL_MONTHS:
        assert service + install + plans == revenue, month
        cogs_labor = round(revenue * 0.31)
        cogs_parts = round(revenue * 0.17)
        gross = revenue - cogs_labor - cogs_parts
        opex = [("Officer compensation", 9_500), ("Office salaries and benefits", 24_800),
                ("Rent", 7_200), ("Vehicle fuel and maintenance", round(revenue * 0.026)),
                ("Insurance", 4_150), ("Advertising", round(revenue * 0.018)),
                ("Software and phones", 1_680), ("Consulting fee, R. Kowalski", 0 if month == "2026-07" else 6_000),
                ("Depreciation", 5_900), ("Other operating expenses", round(revenue * 0.012))]
        total_opex = sum(a for _, a in opex)
        operating = gross - total_opex
        interest = round(LOAN * 0.1025 / 12) if month != "2026-07" else 0
        net = operating - interest
        rows = [["Line", "Amount"],
                ["Revenue, service", service], ["Revenue, installation", install],
                ["Revenue, maintenance plans", plans], ["Total revenue", revenue],
                ["Cost of sales, technician labor", cogs_labor], ["Cost of sales, parts and equipment", cogs_parts],
                ["Gross profit", gross]]
        rows += [[name, amt] for name, amt in opex]
        rows += [["Total operating expenses", total_opex], ["Operating income", operating],
                 ["Interest expense, SBA loan", interest], ["Net income", net]]
        path = PNL / f"pnl_{month}.csv"
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["# Brightline Heating & Air, monthly profit and loss", month])
            w.writerow(["# SAMPLE, SYNTHETIC DATA. Stand-in for an accounting system export."])
            w.writerows(rows)
        print("wrote", path.relative_to(HERE.parent), "revenue", revenue)


if __name__ == "__main__":
    doc_loi()
    doc_apa()
    doc_note_a()
    doc_note_b()
    doc_standby()
    doc_consulting()
    for args in EMPLOYEES:
        doc_bonus(*args)
    doc_lender()
    doc_funds_flow()
    write_pnl()
