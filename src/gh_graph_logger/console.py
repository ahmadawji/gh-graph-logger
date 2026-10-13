"""Terminal formatting and console helpers for gh-graph-logger."""

from __future__ import annotations

import sys
from typing import Any


def format_status(success: bool) -> str:
    """Format check status with check/cross or [OK]/[FAIL] based on stdout encoding."""
    symbol = "✅" if success else "❌"
    fallback = "[OK]" if success else "[FAIL]"
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        symbol.encode(encoding)
        return symbol
    except UnicodeEncodeError:
        return fallback


def safe_print(text: str, file: Any = None) -> None:
    """Print text safely, replacing unencodable characters if needed."""
    target_file = file if file is not None else sys.stdout
    encoding = getattr(target_file, "encoding", None) or "utf-8"
    try:
        print(text, file=target_file)
    except UnicodeEncodeError:
        safe_encoded_text = text.encode(encoding, errors="replace").decode(encoding)
        print(safe_encoded_text, file=target_file)


def prompt(question: str, default: str | None = None) -> str:
    """Prompt the user for input via stdin with an optional default value."""
    if default:
        prompt_text = f"{question} [{default}]: "
    else:
        prompt_text = f"{question}: "

    try:
        response = input(prompt_text).strip()
    except EOFError:
        raise KeyboardInterrupt() from None

    if not response and default is not None:
        return default
    return response
