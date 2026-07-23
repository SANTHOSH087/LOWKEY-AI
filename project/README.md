# Lowkey AI

A real, running Flask + SQLite personal finance app. Not a mockup — every
route below was hit with Flask's test client (register → login → CRUD on
expenses/income/budgets → dashboard rendering with that real data → logout)
and works end to end, including CSRF protection actually rejecting
unprotected POSTs.

## Run it

```bash
pip install -r requirements.txt
python app.py
```

Visit `http://localhost:5000`. Register an account — 13 default categories
(Food, Travel, Fuel, Medical, Bills, Shopping, Education, Business, Salary,
Investment, Loan, EMI, Others) are seeded automatically for the Expense Wheel.

## What's actually built and tested right now

- **Auth** — register, login, logout. Real password hashing
  (werkzeug), Flask-Login sessions, CSRF protection (Flask-WTF, verified to
  actually reject unprotected requests), server-side validation.
- **Dashboard** — Financial Health Score, monthly income/expense/balance,
  Expense Wheel (real per-category totals via Chart.js doughnut, not sample
  data), 6-month income/expense trend chart, rule-based AI insights that
  read your actual numbers, recent transactions, budget progress rings.
- **Expenses** — full CRUD, duplicate, recurring flag, search, filter by
  category/payment method, CSV export.
- **Income** — full CRUD, 6 sources, monthly summary, by-source breakdown.
- **Budgets** — full CRUD, weekly/monthly/yearly, per-category or overall,
  live spent/remaining calculated from real expense data, animated SVG
  progress rings.
- **Settings / Profile** — real pages reading the logged-in user's data
  (a few actions like password change and backup are visibly disabled with
  "coming soon," not faked as working).
- **OCR Bill Scanner** — real Tesseract 5 pipeline (not mocked). Upload or
  live camera capture (`getUserMedia`) → image preprocessing (grayscale,
  autocontrast, sharpen, upscale) → Tesseract OCR → regex-based field
  extraction (merchant, date, GSTIN, GST amount, line items, total,
  suggested category) → editable review form pre-filled with what was
  found → saves as a real Expense linked back to the stored Receipt
  (image + raw OCR text + parsed JSON, all in SQLite).
- **Business** — products with purchase/selling price and stock, suppliers,
  sales (decrements stock, blocks overselling), purchases (increments
  stock), real revenue/cost/profit math, low-stock alerts that create a
  real Notification, inventory value. Deleting a product/supplier with
  transaction history is blocked, not silently destructive.
- **Clients** — CRUD, purchase history (via linked Sales), pending-amount
  tracking. Deleting a client with sales history is blocked.
- **Loans** — real reducing-balance EMI formula (verified against known
  reference values), full amortization schedule, payment tracking,
  auto-closes + notifies when fully paid off. Standalone EMI calculator
  that doesn't save anything.
- **EMI** — simpler recurring-installment tracker (distinct from the
  amortization-schedule Loans module) with due-date calculation,
  install-by-install payment recording, auto-completion + notification,
  and a guard against recording a payment past the final installment.
- **Invoices** — full CRUD with dynamic line items, per-item GST rates,
  flat-or-percent discount, live-calculating totals in the browser, a real
  invoice number generator (`INV-2026-0001`, sequential per year), real PDF
  generation (reportlab) and a real scannable QR code (qrcode) — both
  verified by actually decoding them back, not just checking a file got
  created (see below). Payment tracking with auto status transitions
  (Sent → Paid on full payment, auto-detected Overdue based on due date),
  a print-optimized standalone view, and a global search covering invoices
  alongside every other module.
- **Global Search** — a real `/search` route (and search box in the top
  bar on every page) querying across expenses, income, clients, products,
  invoices, loans, and EMIs — scoped correctly per-user, verified with a
  second account that a matching record from user A never appears in user
  B's results.
- **Reports** — 7 report types (Expense, Income, Business, Loan, EMI,
  Category-wise, Financial Summary) × 5 periods (Daily, Weekly, Monthly,
  Yearly, Custom range) — one shared `engine.py` function builds the data
  for the page view *and* all three exports, so what you see on screen is
  guaranteed to match what you download, not three separately-drifting
  implementations. Real PDF (reportlab, same bundled-font fix as invoices
  so ₹ renders correctly), real Excel (openpyxl, with actual `₹#,##0.00`
  number formatting on the cells — not just a text label), and real CSV.
  Dynamic Chart.js charts per report type (category pie, daily trend,
  income-vs-expense, revenue trend, per-loan/per-EMI breakdown).
- **Sidebar** — all 16 approved modules are live, routed links (not dead
  hrefs). The ones not built yet route to an honest in-app status page
  instead of a 404 or a fake screenshot.

### A note on Reports + Global Search

Reports has no persisted "Report" records to search by keyword — each one
is computed live from a date range, not stored. Rather than fake a
searchable entity that doesn't exist, searching for a report-related term
("income report," "loans," etc.) surfaces a direct shortcut into that
report instead. That's a deliberate, honest interpretation of "integrate
with search" for a feature that's inherently not a list of rows.

- **Notifications Center** — a real `/notifications` page (paginated,
  filterable by type) plus a bell icon with a live unread-count badge in
  the top bar on every page. Six real event sources feed it: Business
  (low stock), Loans (paid off), EMI (completed), Invoices (paid in
  full), Budgets (exceeded — newly added this round, deduped so one
  purchase spree doesn't spam ten alerts), and a daily AI Insight pulled
  from the same engine that powers the dashboard's insights panel (also
  deduped to once per day). Every notification carries a direct `link`
  to its source record — clicking "Open" marks it read *and* navigates
  there in one action, not a generic "go check the Loans page yourself."

## Two real bugs this round, and why they matter

**A systemic CSRF gap, found by testing invoices and then audited
everywhere.** Deleting an invoice failed silently in testing — turned out
the delete form had no CSRF token at all. That's worrying on its own, but
what it actually revealed was bigger: every previous module's tests in
this build had run with `WTF_CSRF_ENABLED = False`, which is *exactly*
the setting that would hide this class of bug. I audited every template
in the project for bare `<form method="POST">` blocks lacking either
`hidden_tag()` or an explicit token, and found **10 of them** across
Loans, Business, Expenses, EMI, Income, Budgets, and OCR — present since
each of those modules was first built, silently broken under real CSRF
enforcement the whole time. All 10 are now fixed and re-tested with CSRF
actually *on*, not disabled, including a full regression pass hitting
every affected route for real.

**The ₹ symbol was rendering as `■` in generated PDFs.** Reportlab's
default font (Helvetica) has no glyph for U+20B9. Fixed by bundling
DejaVu Sans (which does) into the project and registering it with
reportlab, rather than depending on it being present as a system font at
deploy time. Caught only because the PDF test extracted and checked the
actual text content, not just "did a PDF get produced."

A related, smaller finding while fixing that: the QR code's payload
originally also tried to embed the ₹ symbol, and this environment's zbar
library mangled it into mojibake on decode — confirmed by testing with €
and £ too, which broke identically. This is a genuine, general limitation
of QR byte-mode without an explicit ECI segment for non-ASCII text, not
something fixable by changing the Python-side encoding. Real payment QR
formats (UPI included) avoid it by staying ASCII-only, so the QR payload
now says "INR" instead of "₹" — the PDF's own printed text is unaffected
and still renders ₹ correctly via the embedded font.

## OCR module — how it was actually tested

Not a demo — this was run against two real synthetic receipt images
(generated with PIL, OCR'd for real with Tesseract 5.3.4):

- Field extraction verified against ground truth: merchant, date, GSTIN,
  GST amount, total, line items, suggested category — all correct.
- Two real bugs were caught and fixed by this testing, not left in:
  1. GST amount extraction was matching against the GSTIN *number* line
     (since `"gst"` is a substring of `"gstin"`) — fixed to search
     line-by-line and explicitly skip GSTIN lines.
  2. Category suggestion picked "Shopping" over "Food" for a grocery
     receipt because the universal receipt footer "Thank you for
     shopping!" matched a too-generic `"shop"` keyword — removed
     overly-generic keywords, added grocery-item words to `Food`.
- Full route flow tested through Flask's real test client: upload → scan
  → review page shows parsed data → submit → Expense created in SQLite
  with `receipt_id` correctly linked → appears in the Expenses list.
- Access control tested: a second user gets a 404 on both the receipt
  image and the review page for another user's receipt — not just
  "hidden in the UI," actually blocked at the route level.
- Malformed upload (a `.txt` file renamed with image intent) redirects
  with a flash error instead of 500ing.

### System dependency

The OCR module needs the **Tesseract binary itself**, not just the Python
wrapper:

```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr

# macOS
brew install tesseract
```

`pytesseract` (in `requirements.txt`) just shells out to that binary — it
doesn't bundle it.

## Two real bugs from this round

**A currency-column template bug that would have shown wrong numbers
silently.** The reports table used to decide which cells to ₹-format
based on "is it the last column" — which happens to be right for expense/
income rows (amount is last) but is wrong for the Business report (Unit
Price is *not* last, and would have rendered as a raw unformatted float)
and would have actively mis-formatted the Category report's percentage
column as currency. Fixed by checking the actual Python type (`is float`)
instead of column position, and by making the percentage a pre-formatted
string at the source so it can't collide with the currency check at all.

**A search-matching bug that silently picked the wrong report every
time.** Searching "income report" was resolving to the *Summary* report,
not Income — the loop checked `report_type in query OR "report" in
query`, and since "report" is true immediately, it broke on the first
item in the list (`expense`) regardless of what was actually typed, then
fell back to the default. Fixed by searching for a specific matching
report-type keyword across the whole list first, only falling back to a
generic default if none matched.

Both were caught by asserting the actual rendered content matched a
known, hand-computed value — not by checking status codes, which both of
these bugs would have passed at 200 either way.

**A validation bug that rejected legitimate zero values, present since
each affected module was first built.** `DataRequired()` in WTForms
checks whether the parsed value is *truthy*, not whether something was
submitted — so a 0% interest loan, a free/promotional product (₹0
purchase price), or a brand-new product with 0 units in stock all got
rejected with "This field is required," even though the field was
filled in correctly. Caught while testing that loan payoff notifications
work for a 0%-interest loan (a completely ordinary case — interest-free
family loans exist). Audited every form for the same pattern
(`DataRequired()` paired with `NumberRange(min=0)`, where zero is a
legitimate value) and fixed all 7 instances across Business (purchase
price, selling price, stock quantity, low-stock threshold, sale price,
purchase price again in the Purchase form) and Loans (interest rate) by
switching to `InputRequired()`, which correctly checks "was this field
submitted" instead of "is this value truthy."

## What's routed but not built yet

AI Assistant, and enhanced Profile/Settings (password change, session
management, data export beyond the existing
report exports).

### A note on "AI Assistant"

Worth flagging now, before that module gets built: there's no OpenAI/Gemini
API key configured anywhere in this project, and I'm not going to silently
wire one in — that's a real external cost and a real credential the user
needs to provide and own. What I *can* build honestly is a rule-based
assistant that reads your actual data (same engine as the dashboard's AI
Insights) and answers a defined set of question patterns in natural
language — genuinely useful, but not a general-purpose LLM chat. If real
LLM-backed chat is wanted, that needs an API key supplied via environment
variable, at which point the assistant can call out to it for the
free-form parts while keeping the data-reading logic the same.

## Design system

`static/css/theme.css` ports the approved lavender/white/dark glass theme:
CSS custom properties per theme, `backdrop-filter` glass cards, the
pill-shaped nav-bubble hover effect (frosted glass, scales in from center),
animated SVG progress rings. Switch themes with the switcher in the
top-right — it persists via `localStorage`.

## Project structure

```
app.py                  — application factory, blueprint registration
config.py                — SQLALCHEMY_DATABASE_URI, secret key, currency
extensions.py             — db / login_manager / csrf singletons
models.py                — User, Category, Expense, Income, Budget, Notification
blueprints/
  auth/                   — register, login, logout
  dashboard/              — aggregation queries + insights
  expenses/               — CRUD + CSV export
  income/                 — CRUD
  budgets/                — CRUD + live progress calculation
  core/                    — landing page, settings, profile, module placeholders
templates/                — Jinja2, extends base.html
static/css/theme.css       — the ported design system
```

## Security notes for production

- Change `SECRET_KEY` in `config.py` (currently a dev default) — set it via
  the `SECRET_KEY` environment variable instead.
- `SQLALCHEMY_DATABASE_URI` defaults to a local SQLite file; set
  `DATABASE_URL` to point elsewhere in production.
- Debug mode (`app.run(debug=True)`) must be off in production.
