# scraper3 — Instagram-reachable business leads (India-wide)

Finds small business owners whose **only web presence is a social page**. Their
Instagram *is* their website — which makes the handle both the qualifying signal
(they need a real site / content help) and the contact channel (you can DM
them, for free, without cold calling).

Targeting notes:
- **India-wide** — the old NCR-only gate is gone; DM outreach is delivered
  remotely, so every Indian city is equally workable (searches stay
  country-locked to India).
- **No beauty vertical** — salons, nail studios, spas and makeup artists are
  already extremely content-efficient on Instagram and are dropped at the
  source (`BEAUTY_KEYWORDS`, whole-word matched).

## DM mode (what the launcher's Social Media button runs)

```powershell
python main.py --category-name "cafe" --dm-out leads.xlsx   # top 10 DM leads
python main.py --list-categories                            # dropdown source
```

Sources one category, keeps only Instagram-reachable businesses, takes the best
10 (Goldenrod quality first, then most-reviewed) from a 30-candidate pool, and
writes a sheet where the **DM column opens their Instagram chat directly**
(`ig.me/m/<handle>`) and the Profile column opens the account for a ten-second
vet. Picked rows are recorded in the master file, so every run returns fresh
handles.

Before picking, one batched Apify Instagram-profile call checks every
candidate: **private and non-existent accounts are dropped** (public profiles
only), and so is any business already posting at ≥ `ACTIVE_POSTS_PER_WEEK`
(default 4) — a page shipping reels near-daily has content handled and will
never buy content help.

## Why this repo exists

`/scraper` finds businesses **with** a stale website (email them).
`/scraper2` finds businesses with **no** website at all (phone-only — 0 of 24 rows
in its output had an email address).

Neither can see the businesses in between, and they are the best leads:

- `scraper2/target_sourcer.py` drops any place carrying a `websiteUri`, and asks
  Apify for `website: "withoutWebsite"`. A salon whose Maps website field is
  `instagram.com/salonxyz` looks like "has a website" → **dropped**.
- `scraper/config.py` blocklists `instagram.com` as an aggregator domain →
  **dropped**.

So a no-website, Instagram-native business falls straight through the crack
between the two. This repo catches it.

## How to run

```powershell
pip install -r requirements.txt
copy .env.example .env            # optional; --mock needs nothing

python main.py --mock --no-email  # zero-config smoke test
python main.py --limit 25         # real run, capped
python main.py --category 3       # preselect category (skips the menu)
```

Python 3.10+.

## The one idea: three-way web presence

`web_presence.py` replaces the old binary *"website present ⇒ drop"*:

| Presence | Meaning | Action |
|---|---|---|
| `real` | has an actual website | **drop** — that's `/scraper`'s lead |
| `social` | only an Instagram/Facebook page | **keep**, extract the handle |
| `none` | nothing at all | keep, flag `Phone only` |

A place with a real site *and* an Instagram is `real` — already online, not a
prospect. "Any non-social host wins."

## Architecture

| File | Role |
|---|---|
| `main.py` | Orchestrator, category menu, strict gate, tiering, master upsert |
| `web_presence.py` | `classify()` / `instagram_handle()` — the core distinction |
| `config.py` | Env, Instagram-native categories, blocklists |
| `target_sourcer.py` | Apify → Places API → `seed_places.csv` → mock |
| `http_client.py` | Retry/backoff/jitter + rotating proxy pool |
| `master_registry.py` | The shared `Projects/leads_master.xlsx` writer + dedup |
| `delivery.py` | Resend — mails the master **to you**, never to a prospect |

**Two independent axes, kept apart on purpose.** `Lead Type` is quality
(Goldenrod = rating ≥ 4.5 **and** 500+ reviews / New Bark). Reachability is
implied by the master's `Instagram` column — a handle means you can DM them, a
blank means phone-only. They are *not* merged into one tier string: `stats` is
seeded with exactly the two Lead Type keys, so a third would `KeyError`.

Reachability dominates the write order. A 5-star Goldenrod you can only phone is
useless to a DM-only workflow, so phone-only rows land below every
socially-reachable row regardless of tier.

`--limit` truncates **sourced targets**, before the pipeline knows which carry a
handle. Cap it and you may discard most of your DM-reachable leads while keeping
phone-only ones — and the Apify credits are spent either way. Prefer no `--limit`
on a real run.

## Gotchas worth knowing

- **Apify must be asked for `website: "allPlaces"`.** `"withoutWebsite"` makes
  the actor strip social-only places server-side, before you ever see them. That
  returns more items per sweep, so `APIFY_MAX_SEARCHES` defaults to a tight `12`.
- **The social URL's field is not contractual.** `_apify_url_candidates()` reads
  the union of `website`, `instagrams[]` and `facebooks[]` rather than betting on
  one. It deliberately excludes `item["url"]` — that's the `google.com/maps`
  listing URL, and feeding it in would classify every place as `real`.
- **The Places API is a weak fallback.** It exposes only `websiteUri` and no
  social fields, so it spots a social-only business *only* when the owner put
  their Instagram URL in that slot. Prefer Apify.
- **`EXCLUDED_KEYWORDS` is substring-matched against the category label**, so a
  category containing `digital`, `tech`, `website`, `social media`, `marketing`,
  `branding`, `seo`, or `graphic design` silently returns nothing. `photographer`
  and `interior designer` are safe (the blocklist holds `graphic design`/`web
  design`, not bare `design`).
- **Mock targets are fictional, on purpose.** `/scraper`'s mock list points at
  `livspace.com` and `haldirams.com`, and those real corporate inboxes got
  harvested into its real output CSVs. Never put a live company in `MOCK_TARGETS`.

## Output: the one master workbook

Leads go straight into **`Projects/leads_master.xlsx`** (`master_registry.py`),
the single file shared by all four repos. There is no `output/` folder, no
per-run CSV or XLSX, and no per-repo registry.

`upsert()` skips businesses already in the master, keyed on email, then Instagram
handle, then phone. The business name is a last resort, used only when a row has
none of those — two branches of "Looks Salon" share a name but not a phone.

`/email-automation` reads that file and writes back three columns: `Message`,
`Reached`, `Do Not Contact`. Scrapers never touch those; it never touches theirs.

**`--mock` refuses to write to the master**, so a smoke test can't put a
fictional business in front of a real prospect. Override `MASTER_FILE` to a
scratch path if you want a mock run to persist.
