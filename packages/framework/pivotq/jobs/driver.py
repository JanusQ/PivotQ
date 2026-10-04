"""Run a PivotQ job: ``python -m pivotq.jobs.driver``."""
from __future__ import annotations
from collections.abc import Iterable


def main(argv: Iterable[str] | None = None) -> int:
    from pivotq._internal.jobs.driver import main as run
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
