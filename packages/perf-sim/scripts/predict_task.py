"""Compatibility command; install pivotq before invoking this script."""
from pivotq._internal.performance.cli_task import *

if __name__ == "__main__":
    raise SystemExit(main())
