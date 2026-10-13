"""Standard exit code constants for gh-graph-logger CLI."""

from __future__ import annotations

OK: int = 0
ERROR: int = 1
# Note: Exit code 2 is reserved by argparse for CLI usage errors.
GUARD_FAILED: int = 3
ABORTED: int = 4
