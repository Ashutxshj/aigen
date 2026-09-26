# Murica — Old-Website USA Finder

Pick ONE US state → Google Maps businesses that own their **own** website →
WHOIS the domain → keep only sites whose domain is **10+ years old** →
famous brands and already-web-savvy niches filtered out → **10 valid leads
per run**, each with a one-line redesign pitch → styled XLSX emailed to you
via Resend.

Nothing here contacts a lead. The single outbound email goes to YOUR inbox
(`ashutosh06066@gmail.com`); the Message column is what you send by hand.

## How a run works

1. **Source** — Apify Google Maps Scraper (`compass/crawler-google-places`),
   country-locked to the US, actor-side `withWebsite` filter. Queries are
   `"{category} in {state}, USA"` over a rotating slice of 24 SMB categories
   (law firms, dentists, plumbers, funeral homes, …) — `progress.json`
   remembers each state's rotation offset so repeat runs bill NEW searches.
2. **Filter** (free, before any WHOIS):
   - platform "websites" (facebook, wix, yelp, linktree, …) → out
   - `EXCLUDED_KEYWORDS` (beauty/salon/fashion, digital marketing, tech,
     photographers, architects — anyone who already lives off a good site) → out
   - `famous_brands.csv` (~600 MNCs/chains, matched on name AND domain) → out
   - one lead per domain, and `seen.json` drops anything ever sheeted before
3. **WHOIS gate** — RDAP (`rdap.org`) first, classic port-43 WHOIS fallback,
   answers cached forever in `age_cache.json`. Walks candidates until
   **10** domains prove ≥ `MURICA_MIN_AGE_YEARS` old.
4. **Deliver** — one-line pitch per lead (template, no LLM), styled sheet
   sorted oldest-site-first, emailed via Resend.

## Cost control

Apify is the only billed step: at most `MURICA_MAX_SEARCHES` (6) ×
`MURICA_PLACES_PER_SEARCH` (25) = 150 crawled places per run, state-scoped.
WHOIS/RDAP is free. The knobs use `MURICA_*` env names so scraper2's bigger
caps never leak in through the .env fallback chain.

## Usage

```
python main.py --state Texas                     # scrape, whois, sheet, email
python main.py --state Texas --no-email --out x.xlsx
python main.py --list-states                     # for UIs (the launcher)
python main.py --state Texas --mock              # demo targets, no keys
python main.py --state Texas --fresh             # ignore seen.json this run
```

Keys: `.env` (see `.env.example`), falling back to `launcher/.env` then
`scraper2/.env` — so it runs out of the box with no key copied anywhere new.

## Launcher

Wired as button 7 ("Murica") in `/launcher` — pick a state from the card's
dropdown, click, and the sheet lands in your inbox.
