# Niche

Pick ONE business niche (e.g. **restaurants**) and get an Excel sheet of Indian
businesses in that niche that have **no website**, each with a strictly
one-line pitch ready to send as a digital-marketing-agency opener. The sheet is
emailed to you via Resend; nothing here ever contacts a lead.

## Architecture

Niche is a one-shot CLI — no server, no scheduler, no daemon. One run = one
niche = one sheet = one email to yourself. There is no LLM anywhere in this
repo: the pitch is a deterministic template, which makes every run free,
instant and predictable.

```
                    .venv\Scripts\python main.py --niche restaurants
                                       │
                                       ▼
 ┌─────────────────────────────── main.run() ────────────────────────────────┐
 │                                                                           │
 │  1 · SOURCE          sourcer.source_targets(niche)                        │
 │      ┌─────────────────────────────────────────────────────────────────┐  │
 │      │  APIFY_TOKEN set?                                               │  │
 │      │    ──► Apify actor compass/crawler-google-places                │  │
 │      │        "{niche} in {city}" over the first APIFY_MAX_SEARCHES    │  │
 │      │        of 15 Indian cities · countryCode=in ·                   │  │
 │      │        website=withoutWebsite (filtered actor-side to save     │  │
 │      │        credits) · deliberately NO retry (a retry re-bills      │  │
 │      │        a paid actor run)                                       │  │
 │      │  else GOOGLE_PLACES_API_KEY set?                               │  │
 │      │    ──► Places API (New) Text Search, all 15 cities,            │  │
 │      │        ≤3 pages each, anything with a websiteUri dropped       │  │
 │      │  else                                                          │  │
 │      │    ──► built-in mock targets (runs with zero keys)             │  │
 │      └─────────────────────────────────────────────────────────────────┘  │
 │             │  _dedupe(): key = place_id or name|address ·               │
 │             │  drop blank names · drop EXCLUDED_KEYWORDS hits            │
 │             │  (digital/seo/web-design agencies are peers, not           │
 │             │  prospects) · cap at MAX_TARGETS                           │
 │             ▼                                                            │
 │  2 · DEDUP vs HISTORY   seen.json — every business ever sheeted          │
 │             │           new = targets not in seen  (--fresh skips this)  │
 │             │           0 new → exit, no sheet, no email                 │
 │             ▼                                                            │
 │  3 · PITCH   pitch.one_liner(target, niche)     ← no LLM                 │
 │             │  social proof picked by what exists:                       │
 │             │    rating + ≥50 reviews  → "your 4.5-star rating and       │
 │             │                            620+ reviews show…"             │
 │             │    rating only           → "solid 4.5-star presence…"      │
 │             │    neither               → "you're on Google Maps but…"    │
 │             │  + niche-specific benefit word (diners / patients /        │
 │             │  bookings / …) · collapsed to EXACTLY one line ·           │
 │             │  no em dashes (they read as machine-written)               │
 │             ▼                                                            │
 │  4 · SHEET   sheet.write(out_path, leads)        openpyxl                │
 │             │  columns: Business Name · Category · Phone · WhatsApp ·    │
 │             │  Email · Address · Message                                 │
 │             │  contact-tier sort (phone → email → nothing) ·             │
 │             │  WhatsApp cell = =HYPERLINK("https://wa.me/91…") ·         │
 │             │  frozen header · autofilter · wrap widths                  │
 │             ▼                                                            │
 │  5 · RECORD  seen[key] = {niche, name, at}   (written even on --no-email)│
 │             ▼                                                            │
 │  6 · EMAIL   mailer.send() ──► api.resend.com ──► YOUR inbox             │
 │              (skipped with --no-email; the launcher uses that and        │
 │               mails the sheet itself)                                    │
 └───────────────────────────────────────────────────────────────────────────┘
```

External services: **Apify** (Google Maps actor), **Google Places API (New)**
as fallback, **Resend** for the one email to yourself. `mailer.py` is stdlib
`urllib` only and spoofs a browser User-Agent because Resend sits behind
Cloudflare, which 403s the default `Python-urllib`.

### Config chain

`config.py` loads `.env` files with `setdefault` semantics — first writer wins:

```
 Niche/.env   ──►   ../launcher/.env   ──►   ../scraper2/.env
 (your overrides)   (recipient + Resend,      (the key vault:
                     so the inbox matches      APIFY_TOKEN etc.)
                     every launcher button)
```

Recipient resolution: `NICHE_RECIPIENT` → `RECIPIENT_EMAIL` → hardcoded
fallback.

## Usage

```
.venv\Scripts\python main.py --niche restaurants
.venv\Scripts\python main.py --niche "coaching institutes" --no-email --out x.xlsx
.venv\Scripts\python main.py --list-niches
.venv\Scripts\python main.py --niche restaurants --mock    # no keys needed
.venv\Scripts\python main.py --niche restaurants --fresh   # ignore seen.json
```

---

## The launcher ecosystem

Niche is button **6** of the Chillispark launcher (`../launcher`) — a
stdlib-only localhost web app ("one page, 7 buttons, no terminals") that runs
whichever lead tool you click, isolates only that run's NEW leads, optionally
has `email-automation` draft a cold-outreach message into each row, and emails
the finished sheet to **you**. Nothing in the whole system ever contacts a
lead.

### Full system diagram

```
                 ┌────────────────────────────────────────────────┐
                 │   BROWSER   http://127.0.0.1:8765              │
                 │   launcher/index.html — vanilla JS, no build   │
                 │   7 cards · dropdowns · toasts · 2 s log poll  │
                 └──────┬──────────────────────────────▲──────────┘
                  POST /run/<id>                 GET /status/<id>
                        │                              │
                 ┌──────▼──────────────────────────────┴──────────┐
                 │  launcher/server.py — ThreadingHTTPServer      │
                 │  ONE job at a time (threading.Lock → 409) ·    │
                 │  in-memory JOBS{} · GET /config hides any      │
                 │  button whose tool repo is missing             │
                 └──────┬─────────────────────────────────────────┘
                        │ orchestrator.run(button, jobid, log)
                 ┌──────▼─────────────────────────────────────────┐
                 │  launcher/orchestrator.py                      │
                 │  _run()   Popen per tool venv, streams stdout  │
                 │           line-by-line into the job log        │
                 │  ratelimit.py scans every line → "edit THIS    │
                 │           repo's .env, swap THIS key" toasts   │
                 │  _draft() email-automation --prep (Gemini)     │
                 │  _mail()  Resend → your inbox                  │
                 └─┬────┬────┬────┬────┬────┬────┬────────────────┘
                   │    │    │    │    │    │    │
        button:    1    2    3    4    5    6    7
                   ▼    ▼    ▼    ▼    ▼    ▼    ▼
 ┌─────────┬──────────┬──────────┬─────────┬──────────┬─────────┬─────────┐
 │ scraper │ scraper2 │ scraper3 │  leeds  │leeds-hour│  Niche  │ murica  │
 │ NCR biz │ NCR biz  │ India IG │ intent  │ last-    │ (this   │ US biz  │
 │ w/ STALE│ with NO  │ -only biz│ leads:  │ hour     │  repo)  │ on 10yr+│
 │ website │ website  │ (DM list)│ people  │ wrapper  │ by-niche│ old     │
 │ (sitemap│ (Apify   │          │ who     │ over     │ no-site │ websites│
 │ lastmod │ without- │          │ ASKED   │ leeds    │ leads   │ (RDAP/  │
 │ ≥ 1 yr) │ Website) │          │ for a   │          │         │ WHOIS   │
 │         │          │          │ website │          │         │ age)    │
 └────┬────┴────┬─────┴────┬─────┴────┬────┴────┬─────┴────┬────┴────┬────┘
      │         │          │          │         │          │         │
      ▼         ▼          │          ▼         ▼          ▼         ▼
   APPEND ► leads_master.xlsx      intent_   hour_      writes    writes
   (shared master, schema =        leads     leads      its own   its own
   master_registry.py; launcher    .xlsx     .xlsx      finished  finished
   diffs before/after to isolate                        sheet to  sheet to
   only THIS run's new rows)                            --out     --out
      │                               │
      ▼                               ▼
 ┌────────────────────────────────────────────────────┐
 │  email-automation  ·  main.py --prep               │
 │  Gemini drafts a fact-grounded Message + Channel   │
 │  (email/IG/WhatsApp) into each new row.            │
 │  Pointed at the per-run temp sheet via the         │
 │  MASTER_FILE env var. No --send flag exists,       │
 │  by design, and there must never be one.           │
 │  (buttons 3, 6, 7 skip this — their sheets         │
 │  already contain the message)                      │
 └───────────────────────┬────────────────────────────┘
                         ▼
 ┌────────────────────────────────────────────────────┐
 │  launcher/sheet.py — final presentation pass       │
 │  Source Link as =HYPERLINK in column B · contact-  │
 │  tier sort · strip internal state columns LAST     │
 └───────────────────────┬────────────────────────────┘
                         ▼
        launcher/mailer.py ──► api.resend.com ──► YOUR inbox
        (the single outbound hop in the entire system)
```

### The seven buttons

| # | Label | Tool repo | What it finds | Sheet route |
|---|---|---|---|---|
| 1 | With Website | `scraper` | Delhi NCR businesses whose own `sitemap.xml` says the site is ≥1 year stale | shared master, diffed |
| 2 | Without Website | `scraper2` | Delhi NCR businesses with no website at all | shared master, diffed |
| 3 | Social Media | `scraper3` | India-wide Instagram-only businesses (DM work list) | writes own sheet |
| 4 | Intented | `leeds` | People who publicly asked for a website (Reddit, Stack Exchange, Bluesky, HN, forums, job boards, OSM…), last 48 h | intent sheet, diffed by Permalink |
| 5 | Instant | `leeds-hour` | Same as 4, last hour only | own sheet, diffed |
| 6 | **Niche** | `Niche` | Indian no-website businesses in ONE chosen niche | writes own sheet |
| 7 | Murica | `murica` | US businesses on decade-old websites (RDAP/WHOIS domain age) | writes own sheet |

The launcher builds each dropdown by parsing the tool's `config.py` with
`ast.literal_eval` rather than importing it — every repo has a top-level
`config.py` (name collision) and an import would fire that repo's dotenv side
effects inside the server process. That makes two things in this repo a public
API: **`config.NICHES` must stay a plain list literal**, and **`main.py` must
keep accepting `--niche X --no-email --out PATH`** and write a finished,
message-filled sheet at PATH.

### Two integration contracts

**Contract A — "shared master + diff" (buttons 1, 2, 4, 5).** The tool appends
to a shared workbook (`leads_master.xlsx` / `intent_leads.xlsx`). The launcher
snapshots identity keys before the run (email → Instagram handle → last 10
phone digits → name as last resort, via `master_registry.py`), runs the tool,
re-reads, and set-differences so only this run's new leads are sheeted. Button
4's rows also pass through `launcher/adapter.py`, which converts the intent
schema into the master schema and drops non-India OSM rows.

**Contract B — "write your own finished sheet" (buttons 3, 6, 7).** No shared
state: the tool gets an explicit `--out` path, owns its own dedup
(`seen.json`), and produces a mail-ready sheet. The launcher only runs it,
counts rows, and mails the file. Niche and murica never touch
`leads_master.xlsx` and never import `master_registry`.

### Keys, rate limits, safety

- **Env fallback chain**: Niche and murica hold no keys of their own — both
  walk `own/.env → launcher/.env → scraper2/.env` (first writer wins);
  `scraper2` is the designated key vault. `launcher/.env` sits earlier in the
  chain on purpose so every button mails the same recipient.
- **Rate limiting is detection, not throttling**: `launcher/ratelimit.py`
  regex-matches provider failure phrasings in the streamed logs (Apify,
  Places, Gemini, Resend, per-platform quota lines) and attributes each hit to
  the exact repo `.env` and key name, so the UI toast reads like
  "Edit `scraper2\.env` and swap `APIFY_TOKEN`". This is why Niche's
  `sourcer.py` log phrasings ("Apify returned …", "Apify request failed") are
  load-bearing.
- **Safety invariant, repeated everywhere**: nothing ever contacts a lead
  automatically. Tools run with `--no-email`, `email-automation` has no
  `--send` flag by design, `leeds` has no SMTP client at all. The single
  outbound email per run goes to the operator's own inbox with the sheet
  attached; every message is copy-pasted by hand.

### External services (whole ecosystem)

| Service | Used for | Used by |
|---|---|---|
| Resend | the one email per run, to yourself | launcher, Niche, murica, leeds-hour, scrapers |
| Apify (`compass/crawler-google-places`) | Google Maps sourcing | Niche, murica, scrapers |
| Google Places API (New) | fallback sourcing | Niche, scrapers |
| Google Gemini | drafting only | email-automation, leeds — never Niche or the launcher |
| Reddit / Stack Exchange / Bluesky / HN / OSM | intent-lead collection | leeds |
| RDAP / WHOIS (free) | domain-age gate | murica |

No Google Sheets, no SMTP, no OpenAI/Anthropic anywhere in the system.
