# leeds-hour

One command. The last **hour's** leads — people who just asked online for a
website or SEO help — scored, drafted, written to an Excel sheet in this
folder, and **emailed to you** with the sheet attached.

```bash
python run.py
```

That is the entire interface. It runs once and exits: no loop, no daemon, no
scheduler. Run it whenever you want the freshest possible leads — speed is the
whole edge, and a lead is worth the most in its first hour.

## What it actually is

A thin wrapper around the sibling [`leeds`](../leeds) repo, which must sit next
to this folder. All collection, scoring (Gemini), drafting and safety rules are
imported from there — this repo adds exactly three things:

1. a **one-hour window** over the fast sources only (Reddit, Discourse forums,
   Stack Exchange, Bluesky, Hacker News, Freelancer.com). The slow structural
   sources (OpenStreetMap, new domains, Companies House) move on a timescale of
   days and are deliberately excluded.
2. its **own working store and sheet** (`leads.db`, `hour_leads.xlsx`, both in
   this folder) — it never touches leeds' files, and like leeds it never opens
   `leads_master.xlsx` at all.
3. a **Resend mailer** that sends you the sheet. The only email this repo ever
   sends is a report to *you*; contacting a lead stays a human decision, same
   rule as leeds.

Because the pipeline is imported rather than copied, every improvement to
leeds (kill-phrases, WhatsApp links, the Service-Wanted filter…) applies here
with zero maintenance.

## Setup

```bash
cd ../leeds && pip install -r requirements.txt   # if not already done
cp .env.example .env                             # add your Resend key
python run.py
.\.venv\Scripts\python.exe run.py                # MAIN COMMAND
```

Keys that leeds needs (`GEMINI_API_KEY`, etc.) are read from `../leeds/.env`
automatically.

## Flags

```bash
python run.py --min-score 60     # fewer, better leads in the email
python run.py --no-email         # just write hour_leads.xlsx
python run.py -v                 # show every keep/kill decision
```

## The email

Subject: `leeds-hour: N lead(s) in the last hour`. Body: the top leads with
score, wanted service, age and a link to the post. Attachment: the full
`hour_leads.xlsx` (openers, contact channels, WhatsApp links, your triage
columns). A quiet hour still sends a "0 leads" email — so you know the run
happened rather than failed.

**Resend free-tier caveat:** until you verify a domain at resend.com, mail can
only be sent *from* `onboarding@resend.dev` and only *to* the email address
that owns the Resend account. `RESEND_FROM` / `RESEND_TO` in `.env` are there
for when a domain is verified.

## When to run it

The math from leeds' STRATEGY.md: early replies win, and most competitors
never respond at all. A sensible rhythm is running this at the start of any
work block — the sheet tells you in one glance (Age column) whether anything
is worth interrupting your morning for.
