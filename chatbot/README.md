# leeds

Finds people who — in the last 48 hours — publicly said they need a **website** or
**SEO help**, ranks them, works out what their business is from their own words,
and drafts an opener.

**It never sends anything.** There is no SMTP client, no DM automation, and no
`--send` flag. It fills a spreadsheet. You read it and decide.

---

## Why this exists

The sibling scrapers (`/scraper`, `/scraper2`, `/scraper3`) find businesses that
*ought* to want a website — a stale site, no site on Google Maps, Instagram only.
Every one of those leads is cold. Nobody asked for anything.

This finds the ones who are **asking**. That is a different kind of lead: warm,
timed, and decaying. Someone who posts "opening my bakery next month, no idea how
to get a website" will have picked somebody within days.

It does **not** touch `leads_master.xlsx`. That workbook belongs to the other
repos. This one writes its own sheet, `../intent_leads.xlsx`.

---

## Quick start

**You do not need a Reddit account.** The only key that matters is `GEMINI_API_KEY`
(free). Five of the seven collectors work with no keys at all.

```bash
pip install -r requirements.txt
cp .env.example .env          # GEMINI_API_KEY is the only one you really need

# Offline smoke test — no network, no keys, no spend. Writes its own sandbox
# files (leads.mock.db / intent_leads.mock.xlsx) and never touches the real ones:
python main.py all --mock --dry-run --mock-llm

# The real thing (~30-40 min, mostly Gemini's free tier throttling):
python main.py all --since-hours 48 --min-score 45
```

### Run the stages separately

Each is independent and idempotent, so a failed Gemini call never forces a
re-scrape:

```bash
python main.py collect --since-hours 48        # ~5 min, no LLM
python main.py score                           # the slow one — this is Gemini
python main.py enrich --min-score 45
python main.py draft  --min-score 45
python main.py export --min-score 45           # instant, and free
```

`export` re-reads the DB and rewrites the sheet. Re-run it any time to re-sort or
change `--min-score` without re-scraping or re-spending a single token.

### Flags worth knowing

```bash
--since-hours 6                 # tighter window = much cheaper. Use for frequent runs.
--platform reddit               # one collector only
--areas "Delhi,Gurugram"        # one market only — each Overpass city costs ~2 min
--min-score 60                  # fewer, better leads
-v                              # show every kill/drop decision
```

### Working the sheet

Open `Projects/intent_leads.xlsx`. Sort by **Score** (one blended 0–100 number —
the rule/LLM split lives in the DB, not in your face), then check
**Age (hours)** — past ~24h the post has probably already been answered.

- Rows are identified by **Permalink**. There is no Lead ID, no Posted/Collected
  At (Age says it), and no row whose **Service Wanted** is `none` — if neither
  the model nor the poster's own words can name the service, there is nothing
  to pitch and the row stays out of the sheet.
- **`WhatsApp`** is a click-to-chat `wa.me` link built from the phone number —
  the actionable form of a UK/US number you cannot dial from India. Blank means
  the number could not be normalised with certainty; a wrong link would message
  a stranger, so we never guess.
- **`Contact Channel`** is how you reach them: `public_reply` (Reddit — comment,
  **never** DM), `phone`, `email`, `bid`.
- **`Suggested Opener`** is a drafted *helpful public comment*, not a pitch. Read
  it, edit it, post it yourself. **The tool never sends anything.**
- **`Status` / `Contacted` / `Notes`** are yours. Type in them freely — export
  merges them back before rewriting, so they survive every run.

```
collect → score → enrich → draft → export
```

---

## What it reads

| Tier | Source | Intent | Contact |
|---|---|---|---|
| **1** | **Reddit** (`/new` **and** `/comments`) — **no account needed** | explicit | username only |
| **1** | **Forums** — Shopify / Bubble / Webflow community boards | **explicit** | username only |
| **1** | **Freelancer.com** — web design + SEO projects | maximal | the bid is the channel |
| **2** | **Bluesky** — needs a free app password | stated problem | username only |
| **2** | **Stack Exchange** — webmasters | stated problem | username only |
| **3** | **New domains** — Shopify/Wix placeholders, MX-but-no-site | inferred | none |
| — | **OpenStreetMap** — businesses with a phone and no website | none | **phone ~70%** |

"No website" on the OSM row is **verified, not assumed**: the query and a tag
screen drop anything carrying `contact:website`, `url`, a `brand` (a chain's
site exists whether or not a mapper tagged it) or a `wikidata` id — that purge
removed **349** already-collected "leads" — and the collector then follows the
social links the listing itself gives (`contact:facebook` etc.) looking for a
real website. Found one → not a lead. Facebook/Instagram usually block that
fetch; a *blocked* fetch keeps the lead, because failing to look is not
evidence of absence.
| ~~1~~ | ~~**Hacker News** freelancer thread~~ | **near-dead — see below** | — |

### There is no web-search collector, and you don't need one

A general web search would be the widest net. Every free route to one is a dead
end, and I checked all of them rather than assuming:

- **Google CSE** — free 100/day, but the Cloud console pushes you into a billing
  signup. If you won't hand over a card, that's the end of it.
- **DuckDuckGo Lite** — `robots.txt` *allows* it, but it silently serves an **empty
  results page** to scripts: HTTP 200, zero results, every single query. That's the
  worst possible failure mode and nothing should be built on it.
- **SearX** public instances — 403/429 to anything that isn't a browser.
- **Mojeek, Marginalia** — `robots.txt` **disallows** `/search`. We obey robots.txt.

**`collectors/forums.py` replaces it, and does the job better.** Rather than asking
a search engine to *find* the forum threads, it asks the forums directly — every
Discourse instance ships a public `/search.json`. Verified live: 100 fresh signals
in a 7-day window, including *"Hire someone for help with my Shopify store"* and
*"Why am I getting traffic but no sales?"*

Platform support forums are the prize. The poster has already paid for Shopify or
Webflow, is stuck, and *"is there someone I can just pay to do this?"* is a
sentence that appears constantly. Almost no agencies lurk there — no karma to farm,
no audience to build — so the seller contamination that ruins `r/SEO` is simply
absent. **Adding a forum is one line in `config.DISCOURSE_SITES`.**

Candidates checked and *rejected* (2026-07-12), so nobody re-adds them on a
hunch: Glide/Softr/WeWeb communities respond to `/search.json` but are
developer rooms — Softr has had exactly **one** "hire someone" thread ever;
Squarespace's forum 403s scripts; Framer, GoHighLevel and PrestaShop expose no
Discourse search at all.

**Correction, because an earlier version of this file was wrong:** the monthly HN
*"Freelancer? Seeking freelancer?"* thread was supposed to be the best free
contact source (businesses hiring, with email addresses). It was then actually
checked: the **July 2026 thread had 19 top-level comments — 19 SEEKING WORK, 0
SEEKING FREELANCER.** It is all supply now. The collector still runs and still
filters correctly, but it yields ~nothing. Do not plan around it.

Reddit gives you **intent without contact**. OSM gives you **contact without
intent**. Neither is a whole lead alone — which is why `enrich/` exists.

### Where the leads actually are

Everyone with an agency is refreshing `r/smallbusiness`. Sampling the Reddit
archive says the money is in small **trade and professional** subs, where genuine
"I need a website" threads draw **zero** agency replies — while *offer* posts get
removed by mods 42–69% of the time. The demand side is empty; the supply side is
a graveyard.

`r/Chiropractic` · `r/Dentistry` · `r/Contractor` · `r/Handyman` ·
`r/sweatystartup` · `r/pressurewashing` — these are `SUBS_TIER_A` in `config.py`.
They are also the highest-ticket buyers on the list: a dentist is not haggling
over £400.

See **[STRATEGY.md](STRATEGY.md)** for the full evidence, the qualification
rubric, the openers, and the pricing argument.

### Sources deliberately NOT here

- **LinkedIn.** The most aggressively anti-bot platform on the web. Scraping it
  needs residential proxies and burner accounts that die in days, and it violates
  their ToS. There is no rate-limit setting that makes it safe. If you want
  LinkedIn data, buy it from a licensed vendor.
- **Yelp.** Went paid (Starter $7.99/1k calls; plans from $299/mo).
- **Upwork RSS.** Killed 2024-08-20, never restored. Anything telling you to poll
  it is out of date.
- **Craigslist.** Its `robots.txt` disallows `/search`, and its RSS is served from
  `/search?format=rss`. "Collect Craigslist" and "obey robots.txt" cannot both be
  true. We kept the rule and dropped the source.
- **JustDial.** No API, ToS forbids scraping, blocks hard. Behind
  `ENABLE_JUSTDIAL=1`, off by default, and nothing depends on it.
- **`r/forhire`, `r/webdev`, `r/web_design`.** These are where *supply* lives —
  every post is a competitor. `r/web_design` is ~95% designers. They are in an
  explicit `ANTI_SUBREDDITS` blocklist.

---

## The hard part: buyers vs sellers

On `r/SEO`, the people **selling** SEO outnumber the people **buying** it, and
both use the same nouns. A keyword match on "SEO" returns a list of your
competitors.

So scoring runs in three tiers, cheapest first:

1. **Hard gates** — outside the window, bot author, supply-side sub. Free.
2. **Rule score** — positive phrase banks *and* proximity regexes, against an
   aggressive `HARD_KILL` bank. One kill hit and the row is dead, with no LLM call:
   - **sellers** — "my agency", "DM me", "[FOR HIRE]", "my portfolio"
   - **retrospectives** — `\b(I|we) (built|made|launched)\b`. "I built my site" is
     the single most common false positive in the corpus. Past tense = nothing to sell.
   - **practitioners** — "schema markup", "Core Web Vitals". A shop owner does not
     talk like that.
   - **students, no-budget, salaried job posts**
3. **Gemini** — only for the borderline band. Returns a required
   `role: buyer|seller|peer|student|promoter` and `tense`. Anything not a `buyer`,
   or in the past tense, is dropped **regardless of score**.

The rule score survives on its own. If Gemini is down or unkeyed you still get a
sheet — a model outage must never look like "no leads today".

---

## Anti-ban

The HTTP layer is split in two, because the sibling repos' one-size approach is
actively wrong for APIs:

- **`core/api_http.py`** — persisted token bucket, backoff honouring `Retry-After`,
  and it *reads Reddit's `X-Ratelimit-*` headers and believes them over our own
  config*. A **descriptive bot User-Agent**. No proxies, no jitter: on an
  authenticated API you are identified by your OAuth client id, so rotating IPs
  buys nothing and looks like evasion. Reddit **mandates** the UA shape
  `python:com.chillispark.leeds:v0.1.0 (by /u/you)` and throttles generic ones.
- **`core/scrape_http.py`** — proxy pool, randomised delay, rotating *browser* UA,
  and it **obeys `robots.txt` Disallow** (the sibling scrapers only read robots.txt
  to harvest sitemap links). Used only for HTML nobody gave us an API for.

The token bucket is **persisted in SQLite**, so the budget holds across runs. A
bucket that resets each process will silently double your rate the moment you run
the tool twice in five minutes — which is how keys get suspended.

---

## Known limits — read these

- **Reddit's free API tier is scoped to non-commercial use.** Agency lead-gen is
  commercial. Enforcement is unlikely at this volume, but you should make that
  choice knowingly rather than discover it later.
- **You will not get emails for Reddit users.** ~1-2% expose one, ~0% a phone.
  Anyone claiming otherwise is selling you something. The deliverable there is the
  permalink.
- **WHOIS is redacted post-GDPR**, so `newdomains` gives you a domain, not a person.
- The `Runs` sheet exists so that when yield drops you can see *which collector*
  stopped returning things, instead of guessing.

---

## How to actually land these leads

The scraper is the easy half.

1. **Speed beats everything.** These posts collect a dozen helpful replies within a
   day and the person picks someone in the first few hours. A lead found at hour 40
   of a 48-hour window is dead. Run this every 30 minutes, not once a day. The
   `Age (hours)` column exists to show you, brutally, how late you are.
2. **Reply publicly. Never cold-DM.** An unsolicited pitch DM on Reddit gets you
   reported and shadowbanned, and the account is the asset — lose it and every
   future lead on the platform goes with it. The drafter therefore writes a
   *helpful public comment*, not a pitch, and the validator rejects any draft that
   opens by selling.
3. **Answer the question.** The opener gives away real, specific advice for free.
   If the comment would be worthless with the last line removed, it is a bad comment.
4. **Work the quiet sources.** Everyone with an agency refreshes `r/smallbusiness`.
   Nobody is watching `r/Plumbing`, `r/lawncare`, or the new-domain feed.
5. **A structural lead is not an ask.** Pitching one like an explicit request is
   how you sound like spam. That is why `Intent Tier` is a column.

---

## Safety properties

Two things are enforced and tested:

- **`leads_master.xlsx` is never opened, read, or written.** There is a test that
  asserts its mtime is unchanged after a full run.
- **Your edits survive.** Export reads the existing sheet, merges the human-owned
  columns (`Status`, `Contacted`, `Do Not Contact`, `Notes`) back into SQLite, and
  only *then* rewrites. Without that order, every run would silently erase your
  triage notes. If the file is open in Excel, the write fails **loudly** to
  `intent_leads.new.xlsx` rather than pretending to succeed.
