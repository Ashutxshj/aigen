"""Logging setup. Nothing in this repo calls print()."""

import logging
import sys

_CONFIGURED = False


class _Counter(logging.Handler):
    """Counts WARNING/ERROR records so the run summary can say 'this run was
    not clean' — a failed run must never look like a successful one."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.warnings = 0
        self.errors = 0

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.ERROR:
            self.errors += 1
        elif record.levelno >= logging.WARNING:
            self.warnings += 1


COUNTER = _Counter()


def setup(verbose: bool = False) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        logging.getLogger().setLevel(logging.DEBUG if verbose else logging.INFO)
        return
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S"))
    root.handlers = [handler, COUNTER]
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    _CONFIGURED = True


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
