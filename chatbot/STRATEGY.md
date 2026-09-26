# Turning these leads into paying clients

The scraper is the easy half. This is the half that decides whether it makes money.

Evidence graded throughout. Where a number is vendor marketing or a single
anecdote, it says so. Several widely-repeated "facts" in this space turn out to
be neither.

---

## The three things that matter

### 1. Your price is a bigger threat to this plan than the scraper is

₹20,000 (~$240) does not read as *value* to a US/UK buyer. It reads as **risk**.
Web design is a credence good — the buyer cannot judge quality before purchase,
or reliably even after — so they fall back on cues, and price is the loudest one.

- **Agrawal, Lacetera & Lyons** (*J. Int. Economics*; 424,308 applications across
  14,733 oDesk jobs): applicants from less-developed countries are only **~60% as
  likely to be hired** by developed-country employers, controlling for
  comparables. Crucially, **verified work-history information closes much of the
  gap** — so this is an *uncertainty* problem, not pure prejudice. That means it
  is fixable, and **not by cutting price further**.
- **Shiv, Carmon & Ariely** (*JMR* 2005): discount-primed buyers *actually
  performed worse*. Cheapness degrades the experience, not just the perception.

**Move the Western tier to $800–$1,500 plus a $150–400/mo care-and-SEO retainer.**
That is still a 60–70% discount to a US freelancer — inside "smart procurement",
outside "probably a scam". Keep ₹15k–40k for India. The retainer is what makes the
unit economics survive *and* it answers the buyer's number-one fear (abandonment
after launch). Same lever, twice.

### 2. The winning move is a helpful public comment. Not a DM. Not an offer.

This is not a style preference — it is what the rules permit. r/smallbusiness is
the only major business sub with an opening, and it is exactly this one:

> "You can promote your business in a **relevant reply** to a post or comment in
> other threads providing that **is not the main purpose of your account and it is
> not done repeatedly**."

Both tests are things a mod checks on your profile in ten seconds.

Elsewhere it is a flat no. r/Entrepreneur: *"No dropping URLs, asking users to DM
you, telling people to check your profile… **Violations may result in a permanent
ban.**"* r/webdev: *"We do not allow any commercial promotion or solicitation."*
And r/smallbusiness explicitly names **your free-mockup play as promotion** if you
post it.

**The gate that actually matters is not karma — it is CQS.** Reddit's Contributor
Quality Score uses *"network and location signals"* and whether you verified your
email. The AutoMod snippet business subs copy-paste filters
`contributor_quality: "< moderate"`. **A fresh, unverified, VPN-adjacent account
from India starts at Low and gets silently filtered no matter how much karma you
farm.** Verify your email, use a residential connection, no VPN, no links in early
comments, and accept a ~30-day ramp.

**Cold DMs: don't.** There is zero credible published conversion data for them —
every number in circulation is vendor content marketing. What *is* documented is
the downside: any recipient can one-click Report → Spam, and Reddit's own
self-promotion wiki says *"You should not spam in any way, **especially through
private message**."*

### 3. The uncontested demand is in small trade subs, and it is genuinely unfished

Sampled from the Reddit archive. On **genuine owner demand threads**, pitch-like
replies are near zero — the poster just gets told "use Wix":

| Thread | Comments | Pitches |
|---|---|---|
| r/Dentistry — "Website creator/host?" | 20 | **2** |
| r/Dentistry — "Trying to build a Website myself" | 21 | **0** |
| r/Chiropractic — "website hosts" | 17 | **0** |
| r/Contractor — "Best website platform?" | 26 | **0** |
| r/Handyman — "$500/mo to manage my GBP, website, SEO — worth it?" | 9 | **0** |
| r/Handyman — "just lost an $8k job because I don't have a website" | 584 | **~6** |

Meanwhile *offer* posts in those same subs get removed by mods at **69%
(r/Roofing), 56% (r/Dentistry), 42% (r/HVAC)**. Typical removed title: *"Free
Website For Contractors"*.

**The demand side is empty. The supply side is a graveyard.** That asymmetry is
the entire edge.

**Tier A (point the scraper here):** r/Chiropractic, r/Dentistry, r/Contractor,
r/Handyman, r/sweatystartup, r/pressurewashing. Owner-only populations, real
ticket sizes, and a dentist is not haggling over £400.

**Skip:** r/lawncare (homeowners), r/Construction + r/landscaping (saturated with
website spam), r/KitchenConfidential (kitchen *staff*), r/estimators (one website
post in 18 months), r/forhire (**7 [Hiring] vs 77 [For Hire]** — an 11:1 supply
glut), Fiverr Buyer Requests (killed in 2022), Bark (2.6/5 across 1,644 reviews).

---

## Speed: the famous numbers are fake, but speed still matters

**Do not repeat these.** "78% of customers buy from whoever responds first" has no
study, no sample, no source. The "MIT study" (5-min response = 21× qualification)
is an **InsideSales.com conference deck**, not MIT research — and the same company,
with a far bigger 2021 sample, now reports the effect at ~8×, not 21×. The HBR
"Short Life of Online Sales Leads" piece is a one-page column co-authored by that
company's CEO.

**What is actually solid:**

- **Your competition is asleep.** Mystery-shop audits — the strongest methodology
  available: HBR (n=2,241) found **23% of companies never responded at all**, mean
  42 hours. Drift (n=433) found **55% never responded within five business days**.
  *That* is the argument for speed.
- **Reddit's ranking math has early-mover advantage compiled into it.** From
  Reddit's own `_sorts.pyx`: `order = log10(score); return sign*order +
  seconds/45000`. Newness is worth **+1 point per 12.5 hours**, and because the
  score term is log10, **1 point = a 10× score multiplier**.
- **Early comments win, causally.** Across **86.5M comments**: 17.24% of top-voted
  comments were the *first* comment posted (chance ≈1%); **56% were in the first
  five**. And *Science* (2013), a true randomised experiment on >100,000 comments:
  **a single artificial early upvote → +25% final score.**

**Cadence: poll the ~30–60 subs that matter every 30–60 seconds.** Sub-3-second
detection is engineering vanity — *you* are the bottleneck, and on a low-traffic
trade sub a comment posted 20 minutes in still lands in the first five. **Aim to
be in the first five comments, not the first.** Spend the effort on comment
quality.

⚠️ **Reddit's Responsible Builder Policy (Oct 2025) requires explicit approval
before API access, and prohibits registering multiple client IDs for the same use
case.** Get approved. Do not stack keys.

**Where speed does not help: job boards.** Upwork sorts proposals by "Best Match",
not chronologically. Freelancer.com says **67% of projects get a bid within 60
seconds** — if everyone is fast, speed cannot discriminate. Worse: after an AI
cover-letter tool launched on a large labour platform, the text→callback
correlation **fell 51%** and employers shifted to work history. **Fast plus
templated is now actively penalised.**

---

## The opener

Rules the data supports (cold-*email* data, extrapolated to comments — flagging
that honestly; nobody has run the controlled study on comment→client):

- **Pitching in message #1 cuts reply rates by up to 57%** (Gong, 28M+ emails).
- **25–50 words**, hard ceiling 75. **No links, no images in the first touch.**
- Asking for "thoughts" −20% meetings. ROI language −15%. Guilt ("I never heard
  back") −14%.

**What kills it instantly:** a link. A price. "DM me." "I checked your website and
it's slow." Praise-then-pitch. A calendar link. Template smell. And on Reddit, a
comment history that is 90% pitches — a mod sees that in ten seconds.

### Openers you can use

**Trade sub — "which website builder should I use?"**

> For a handyman site the builder barely matters — what matters is that the phone
> number is the first thing above the fold and it's a tap-to-call link on mobile,
> because that's where most of your traffic lands. Wix or Squarespace both do that
> fine. The thing that actually loses jobs is a contact form that emails an address
> nobody checks. Whatever you pick, forward it to your phone.
>
> Happy to look at the page once you've got a draft up if you want a second pair of eyes.

**SEO — "why am I not ranking for [city] [trade]?"**

> Quick free diagnosis before you spend anything: search your business name in an
> incognito window. If your Google Business Profile shows up with fewer than ~15
> reviews and no service-area categories set, that's almost certainly the whole
> problem, not your website. Local pack ranking is mostly GBP proximity + reviews +
> categories. Fix that first — it's free and takes an afternoon.
>
> If it's already dialled in and you're still invisible, reply with the term you
> want and I'll tell you what the top 3 are doing that you aren't.

**Someone in pain — the "$8k lost job" flavour**

> That specific thing — losing a job because there's nothing to Google — is the most
> fixable problem on this list. You don't need a "real website" to stop it happening
> again this week. A one-page site with your name, service area, three photos of
> finished work, and a tap-to-call button covers 90% of it. Google Business Profile
> does the rest for free.
>
> Have you already got the domain, or starting from zero?

**The only DM shape worth sending — and only AFTER they engaged with your comment**

> Hey — you replied to my comment on the site builder thread. I sketched a rough
> homepage for [business] this morning to show what I meant about the tap-to-call
> thing. Want me to send the screenshot? No pitch attached, genuinely just easier to
> show than describe.

It references a prior interaction (not cold), asks permission (not spam), and
offers an artefact (not a service).

---

## Positioning the India→West gap

**The gap is an asset. The price is a liability. Those are different things.**

The buyer is not pricing your labour, they are pricing **risk** — and the research
says the penalty is bought back by *verified information*, not by cutting price.
So do not hide where you are. **De-risk it.** (Concealment also detonates on the
first video call, converting a discount into a deception.)

The seven fears, well attested in r/smallbusiness horror stories: ghosting
mid-build; **not owning their own site** (dev registered the domain, holds the
logins); timezone black holes; a plagiarised template sold as custom; SEO spam
that gets them penalised; zero post-launch support; being held hostage at renewal.

**Defuse them unprompted, in writing, before they ask:**

> Three things before we talk about money, because they're what goes wrong with
> offshore developers:
>
> **The domain and hosting go in your name, on your card, from day one.** I get
> invited as a user. I never own your assets.
>
> **Payment is in milestones tied to deliverables, not dates** — 25% to start, and
> you approve each stage before the next begins.
>
> **If we part ways at any point, you get a full export and a handover doc within 7
> days, no fee.**

That paragraph is free, no competitor writes it, and it answers the number-one
documented fear. **It is the highest-ROI sentence in this document.**

Credibility, ranked by uncertainty killed per unit of effort: a **live video call
with your face and real name** > the ownership clause above > **milestone payments**
(literally the mechanism the research found closes the gap) > *verifiable* reviews
> live portfolio URLs > a real domain and business email. **A Gmail address on a
$240 quote is fatal.**

Price in USD. Tiered packages, middle one as default. **Never hourly** — it invites
a rate comparison you lose in both directions.

---

## Qualification

Score 0–10. **Below 5, do not spend a comment on it.**

| Signal | |
|---|---|
| Losing money *right now* ("lost an $8k job") | **+3** |
| Poster is an **owner** (history shows a business, not a job) | +2 |
| Real ticket size: dentist, chiro, contractor, HVAC, roofer, law, med-spa | +2 |
| Already owns a domain / pays for hosting or ads — **proof of budget** | +2 |
| Has **paid someone before** (even badly — especially badly) | +2 |
| US/UK/CA/AU/EU | +1 |
| <6h old and <5 comments | +1 |
| Asks a *specific* question | +1 |
| **NGO / charity / nonprofit** — `plan.txt` already learned this the hard way | **−4** |
| Student, "my first project", coursework | −4 |
| Equity-only, revenue-share, "exposure" | **−5** |
| r/slavelabour, r/DoneDirtCheap, any "$80 full site" venue | **−5** |
| "Should be simple / shouldn't take more than a day" | −3 |
| Wants free mockups *before* hiring (spec work) | −3 |
| Refuses to name a budget, or is offended you asked | −2 |

**Five gates before you write a proposal:** Is there revenue? Are you talking to
the decision-maker? Do they own the domain today? Is there a number in their head
within 2× of your floor? **Will they take a 20-minute video call?**

**That last one is the hard disqualifier.** Anyone spending $1,000 who will not
give you twenty minutes on video is not buying. This single gate will save you
more hours than everything else here combined.

---

## Follow-up, and where deals die

**12 million outreach emails (Backlinko × Pitchbox — the strongest dataset here):**
baseline reply **8.5%**; **one follow-up = +65.8% replies**; multi-touch ≈ **2×**.
Note the inversion though: openers must be short, but **follow-ups with 4+
sentences get 15× more meetings** than short ones. The opener earns attention; the
follow-up carries substance.

**Four touches over 14 days. New value each time. Never a guilt bump.**

- **Day 0** — the 25–50-word comment. No link, no pitch, no price.
- **Day 3** — the artefact. A screenshot of a rough homepage, or a 90-second Loom
  of their Google Business Profile. **Screenshot, not link** (`plan.txt` already
  knows this, and it is right).
- **Day 7** — a different angle: the competitor ranking above them, and *why*.
- **Day 14** — close the loop cleanly: *"I'll assume the timing's off — want me to
  check back in Q4?"* Then **stop**. A second bump is where you earn a spam report.

**Where the deal actually dies, in order of frequency:**

1. **You put a price in a DM.** A number with no context is just a number to be
   compared against the next guy's ₹15,000. **Never quote in a chat window.** Get
   verbal agreement in principle on a call, *then* write it up.
2. **You ask for a call too early.** Earn it with the artefact first, so the ask
   becomes *"I already built you a rough homepage — want to walk through it for 15
   minutes?"* That reframes the call as **collecting something they already own**,
   not attending a sales meeting. Biggest conversion lever after the opener.
3. **You never move off Reddit.** Reddit chat is where deals go to die.
4. **You get scoped to death for free.** Stop at one artefact.
5. **Payment terms scare them off.** Counterintuitively: **lower the first
   milestone (25–30%) and add more milestones.** You trade deposit % for the deal
   by capping *their* downside — which is exactly the ghosting fear. Tie money to
   **deliverables, not dates**.

**Getting paid** (verify current rates before quoting; all-in on a $1,000 invoice):
**Wise ~1.9–2.15%** (best for direct invoicing) · **Payoneer ~2–3%** (free digital
FIRA — a real compliance advantage) · **PayPal ~7.4–9%** (only if they refuse
everything else). Get a FIRC/FIRA on every inbound payment — required for tax
filing and GST export zero-rating.

---

## What to do Monday

1. **Raise the Western price to $800–1,500 + retainer.** Costs nothing, ships
   today, and the evidence says it *increases* conversion.
2. **Warm one Reddit account for 30 days.** Verify email, no VPN, join the six
   Tier-A subs, comment helpfully 2–3×/day about anything *except* web design. Not
   one promo comment until day 30. **CQS is the gate, not karma.**
3. **Point the scraper at the Tier-A subs** (already `SUBS_TIER_A` in `config.py`).
   Not r/smallbusiness — everyone is there.
4. **Spend the real engineering money on Google Places `websiteUri = null`.** It is
   the only source where "has no website" is a *verified fact* rather than an
   inference, attached to a name, phone, address and reviews — and **45–56% of
   trades have no website**. It costs money instead of costing competition. For the
   cold-email pipeline this is a bigger, more durable source than the entire Reddit
   play. The Reddit play is high-quality but low-volume; this is high-volume.
5. **Write the ownership-clause paragraph once** and paste it into every deal.

---

## Honest gaps

- **No credible conversion data exists for cold Reddit DMs, or for the
  comment→client pattern.** Everything quantitative in the opener and follow-up
  sections is cold-*email* data being extrapolated. It transfers well in principle
  (length, no pitch, no links) but nobody has run the controlled study.
- **Nobody has published a Reddit-wide median time-to-first-comment.** You can
  compute it yourself off `/r/<sub>/new?limit=100` in about an hour, and you would
  then know more than anyone writing about this.
- Rule text for r/SEO, r/web_design and r/DigitalMarketing could not be fetched —
  open them in a browser before relying on them.
