"""leeds — find people who just said they need a website or SEO help.

    python main.py all --since-hours 48
    python main.py all --mock --dry-run --mock-llm     # offline, no keys, no spend

Stages are independent and idempotent, so a failed Gemini call never forces you
to re-scrape:

    collect -> score -> enrich -> draft -> export

THIS TOOL NEVER SENDS ANYTHING. It fills a spreadsheet. You read it, you decide,
you post the reply yourself. There is no --send flag and there must never be one:
an automated promotional DM is how you lose a Reddit account, and the account is
the asset.
"""

import os
import sys
import uuid
from datetime import timedelta

import typer

import config
from collectors.bluesky import BlueskyCollector
from collectors.directories import DirectoriesCollector
from collectors.forums import ForumsCollector
from collectors.hackernews import HackerNewsCollector
from collectors.jobboards import JobBoardsCollector
from collectors.newdomains import NewDomainsCollector
from collectors.reddit import RedditCollector
from collectors.reddit_public import RedditPublicCollector
from collectors.registries import RegistriesCollector
from collectors.stackexchange import StackExchangeCollector
from collectors.websearch import WebSearchCollector
from core import log
from core.api_http import ApiHttp
from core.gemini import Gemini
from core.models import utcnow
from core.ratelimit import RateLimiter
from core.scrape_http import ScrapeHttp
from core.store import Store
from draft import generate as drafting
from enrich.profile import Profiler
from export import excel
from intent import score as scoring

app = typer.Typer(add_completion=False, help=__doc__)
logger = log.get("main")

# USE_REDDIT_PUBLIC (default ON) reads Reddit through the public Arctic Shift
# archive: no app, no client id, and your Reddit account is never touched. Set
# USE_REDDIT_PUBLIC=0 in .env only if you have credentials and want the official
# OAuth path instead.
_REDDIT = RedditPublicCollector if config.USE_REDDIT_PUBLIC else RedditCollector

COLLECTORS = {
    "reddit": _REDDIT,
    # forums + stackexchange are what a general web search was FOR: they reach
    # the platform-support boards where "is there someone I can just pay to do
    # this" gets posted. Asking the forums directly beats asking Google to find
    # them, and it needs no key and no card.
    "forums": ForumsCollector,
    "stackexchange": StackExchangeCollector,
    "bluesky": BlueskyCollector,
    "hackernews": HackerNewsCollector,
    "jobboards": JobBoardsCollector,
    "directories": DirectoriesCollector,
    "newdomains": NewDomainsCollector,
    "registries": RegistriesCollector,
    # Optional and OFF unless you set a key. Nothing depends on it — see the
    # note in config.py for why every free web-search route is a dead end.
    "websearch": WebSearchCollector,
}


def _mock_variant(path: str) -> str:
    """leads.db -> leads.mock.db, intent_leads.xlsx -> intent_leads.mock.xlsx."""
    root, ext = os.path.splitext(path)
    return f"{root}.mock{ext}"


class Ctx:
    def __init__(self, mock, dry_run, mock_llm, verbose):
        log.setup(verbose)
        # A --mock run must never write the REAL store or the REAL sheet. It
        # used to: the documented smoke test filled leads.db with fixture rows,
        # poisoned the shared llm_cache with mock verdicts (same key space as
        # real ones — a later real run replays them), and overwrote the sheet
        # the human was triaging. Mock runs get their own sandbox files.
        self.store = Store(_mock_variant(config.DB_PATH) if mock else "")
        # In --mock/--dry-run nothing goes out, so there is nothing to pace.
        self.limiter = RateLimiter(self.store.conn, disabled=mock or dry_run)
        self.api = ApiHttp(self.limiter, dry_run=dry_run or mock)
        self.scraper = ScrapeHttp(self.limiter, dry_run=dry_run or mock)
        self.gemini = Gemini(store=self.store, mock=mock_llm or mock)
        self.mock = mock
        self.run_id = uuid.uuid4().hex[:8]

    def collectors(self, only: str = "", areas: str = ""):
        out = []
        for name, cls in COLLECTORS.items():
            if only and name != only:
                continue
            kwargs = {"mock": self.mock}
            if name == "directories" and areas:
                # Each Overpass city costs up to two minutes, so let the caller
                # work one market at a time instead of sweeping all of them.
                kwargs["areas"] = [a.strip() for a in areas.split(",") if a.strip()]
            out.append(cls(self.api, self.scraper, self.store, **kwargs))
        return out


def _since(hours: int):
    return utcnow() - timedelta(hours=hours)


# --- stages -------------------------------------------------------------------

def do_collect(ctx: Ctx, hours: int, platform: str, areas: str = "") -> int:
    since = _since(hours)
    started = utcnow()
    total = 0
    for collector in ctx.collectors(platform, areas):
        signals = collector.run(since)
        added = ctx.store.add_signals(signals)
        total += added
        # collector.errors, not 0: a collector that threw used to be recorded in
        # the Runs sheet as a clean 0-fetched run, i.e. indistinguishable from
        # "there was nothing to find".
        ctx.store.record_run(ctx.run_id, started, collector.name,
                             len(signals), added, 0, collector.errors)
        logger.info("%s: %d fetched, %d new", collector.name, len(signals), added)
    logger.info("collect: %d new signals in the last %dh", total, hours)
    return total


def do_score(ctx: Ctx, hours: int, platform: str) -> int:
    since = _since(hours)
    signals = ctx.store.fresh_signals(since, platform=platform)
    logger.info("scoring %d signals", len(signals))
    leads = scoring.score_all(signals, since, ctx.gemini, ctx.store)
    logger.info("score: %d leads survived (gemini: %d requests)",
                len(leads), ctx.gemini.request_count)
    return len(leads)


def do_enrich(ctx: Ctx, hours: int, min_score: int) -> int:
    since = _since(hours)
    leads = ctx.store.leads(since, min_score=min_score)
    if not leads:
        logger.info("enrich: nothing above score %d", min_score)
        return 0
    # Same class the collector used, so the enricher reads history through the
    # same route (public archive vs OAuth) and never needs a token it hasn't got.
    reddit = _REDDIT(ctx.api, ctx.scraper, ctx.store, mock=ctx.mock)
    profiler = Profiler(ctx.api, reddit, mock=ctx.mock)
    for lead in leads:
        fields = profiler.enrich(lead.signal)
        context = fields.pop("author_context", "")
        ctx.store.save_enrichment(lead.signal.source_uid, **fields)
        lead.signal.raw["author_context"] = context
    logger.info("enrich: enriched %d leads", len(leads))
    return len(leads)


def do_draft(ctx: Ctx, hours: int, min_score: int) -> int:
    since = _since(hours)
    leads = ctx.store.leads(since, min_score=min_score)
    if not leads:
        logger.info("draft: nothing above score %d", min_score)
        return 0
    written = drafting.draft_all(leads, ctx.gemini, ctx.store)
    logger.info("draft: %d openers written, %d need writing by hand",
                written, len(leads) - written)
    return written


def do_export(ctx: Ctx, hours: int, min_score: int) -> str:
    since = _since(hours)
    leads = ctx.store.leads(since, min_score=min_score)
    kept = excel.exportable(leads)
    if len(kept) != len(leads):
        logger.info("export: left out %d rows with Service Wanted = none — "
                    "nothing to pitch there", len(leads) - len(kept))
    path = _mock_variant(config.INTENT_FILE) if ctx.mock else ""
    return excel.export(kept, ctx.store, path=path)


def _summary(ctx: Ctx) -> None:
    errors, warnings = log.COUNTER.errors, log.COUNTER.warnings
    if errors:
        logger.error("RUN WAS NOT CLEAN: %d errors, %d warnings. The numbers "
                     "above are incomplete — do not treat this as a full sweep.",
                     errors, warnings)
    elif warnings:
        logger.warning("run finished with %d warnings", warnings)
    else:
        logger.info("run clean")


# --- commands -----------------------------------------------------------------

M = typer.Option(False, "--mock", help="Use recorded fixtures. No network.")
D = typer.Option(False, "--dry-run", help="Make no outbound requests at all.")
L = typer.Option(False, "--mock-llm", help="Fake Gemini. No spend.")
H = typer.Option(config.DEFAULT_SINCE_HOURS, "--since-hours",
                 help="Recency window. A hard gate, not a preference.")
P = typer.Option("", "--platform", help="Only this collector.")
S = typer.Option(config.MIN_SCORE_DEFAULT, "--min-score")
V = typer.Option(False, "-v", "--verbose")
A = typer.Option("", "--areas",
                 help='Cities for the directory collector, comma-separated '
                      '(e.g. "Delhi,Gurugram"). Each city costs up to ~2 min, '
                      "so use this to work one market instead of sweeping all.")


@app.command()
def collect(since_hours: int = H, platform: str = P, areas: str = A,
            mock: bool = M, dry_run: bool = D, verbose: bool = V):
    ctx = Ctx(mock, dry_run, False, verbose)
    do_collect(ctx, since_hours, platform, areas)
    _summary(ctx)


@app.command()
def score(since_hours: int = H, platform: str = P, mock: bool = M,
          mock_llm: bool = L, verbose: bool = V):
    ctx = Ctx(mock, False, mock_llm, verbose)
    do_score(ctx, since_hours, platform)
    _summary(ctx)


@app.command()
def enrich(since_hours: int = H, min_score: int = S, mock: bool = M,
           dry_run: bool = D, verbose: bool = V):
    ctx = Ctx(mock, dry_run, False, verbose)
    do_enrich(ctx, since_hours, min_score)
    _summary(ctx)


@app.command()
def draft(since_hours: int = H, min_score: int = S, mock: bool = M,
          mock_llm: bool = L, verbose: bool = V):
    ctx = Ctx(mock, False, mock_llm, verbose)
    do_draft(ctx, since_hours, min_score)
    _summary(ctx)


@app.command()
def export(since_hours: int = H, min_score: int = S, verbose: bool = V):
    ctx = Ctx(False, True, True, verbose)
    path = do_export(ctx, since_hours, min_score)
    typer.echo(f"wrote {path}")
    _summary(ctx)


@app.command()
def all(since_hours: int = H, min_score: int = S, platform: str = P,
        areas: str = A, mock: bool = M, dry_run: bool = D, mock_llm: bool = L,
        verbose: bool = V):
    """collect -> score -> enrich -> draft -> export."""
    ctx = Ctx(mock, dry_run, mock_llm, verbose)
    do_collect(ctx, since_hours, platform, areas)
    do_score(ctx, since_hours, platform)
    do_enrich(ctx, since_hours, min_score)
    do_draft(ctx, since_hours, min_score)
    path = do_export(ctx, since_hours, min_score)

    leads = excel.exportable(
        ctx.store.leads(_since(since_hours), min_score=min_score))
    hot = [l for l in leads if l.score >= 70]
    typer.echo("")

    if mock:
        # A mock sheet used to be indistinguishable from a real one, and the
        # fixtures' invented Reddit ids happened to resolve to REAL, unrelated,
        # decades-old posts (Reddit ids are base36, so "aaa3" is a valid id).
        # Clicking a "lead" opened a stranger's 2005 thread. Say plainly that
        # none of this is real.
        typer.echo("  " + "=" * 66)
        typer.echo("  MOCK RUN — these are NOT real leads.")
        typer.echo("  Everything below came from fixtures/. The permalinks point")
        typer.echo("  at mock.invalid on purpose and will not open.")
        # Reddit needs NO account (see collectors/reddit_public.py) — telling the
        # user to go make one is the exact advice this repo exists to disprove.
        typer.echo("  For real leads you only need GEMINI_API_KEY in .env.")
        typer.echo("  Reddit needs no account. Then run:  python main.py all")
        typer.echo("  " + "=" * 66)
        typer.echo("")

    typer.echo(f"  {len(leads)} leads  ({len(hot)} scoring 70+)")
    typer.echo(f"  window: last {since_hours}h")
    typer.echo(f"  gemini: {ctx.gemini.request_count} requests")
    typer.echo(f"  sheet:  {path}  (times shown in {config.DISPLAY_TZ_NAME})")
    typer.echo("")
    if not mock:
        typer.echo("  Open the sheet, click a permalink, read the post before "
                   "you reply to it.")
        typer.echo("  Reply publicly and helpfully. Do not cold-DM. Nothing "
                   "here has been sent.")
    _summary(ctx)
    if log.COUNTER.errors:
        sys.exit(1)


if __name__ == "__main__":
    app()
