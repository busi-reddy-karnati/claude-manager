"""Generate one-line session summaries with Claude, and cache them.

Because ``claude`` is already installed and authenticated, we reuse it in
non-interactive print mode (``claude -p``) to summarise each session — no
separate API key required. A fast model (Haiku by default) keeps it cheap.

Summaries are cached on disk keyed by session id + a content fingerprint, so a
session is only re-summarised when it actually changes.

Configuration:
    CLAUDE_MANAGER_SUMMARY_MODEL   model alias/id   (default: haiku)
    CLAUDE_MANAGER_CLAUDE_BIN      claude binary    (default: claude)
    XDG_CACHE_HOME                 cache location   (default: ~/.cache)
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from claude_manager.core import Session, read_transcript_text

DEFAULT_MODEL = "haiku"
_MAX_SUMMARY_CHARS = 80


class SummaryError(RuntimeError):
    """Raised when a summary could not be generated."""


def resolve_model(model: str | None = None) -> str:
    """Pick the model for summaries.

    Order of preference:
      1. an explicit ``model`` argument (e.g. ``--model``),
      2. ``CLAUDE_MANAGER_SUMMARY_MODEL``,
      3. ``ANTHROPIC_SMALL_FAST_MODEL`` — the small/fast model your Claude Code
         is already configured with, so summaries work out of the box on managed
         backends (Bedrock, Vertex, Azure Foundry) without extra setup,
      4. the ``haiku`` alias.
    """
    return (
        model
        or os.environ.get("CLAUDE_MANAGER_SUMMARY_MODEL")
        or os.environ.get("ANTHROPIC_SMALL_FAST_MODEL")
        or DEFAULT_MODEL
    )


def cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "claude-manager" / "summaries.json"


class SummaryCache:
    """A small JSON cache: session_id -> {summary, fingerprint}."""

    def __init__(self, path: Path | None = None):
        self.path = path or cache_path()
        self.data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data = loaded
        except (OSError, json.JSONDecodeError):
            self.data = {}

    def get(self, session: Session) -> str | None:
        entry = self.data.get(session.session_id)
        if entry and entry.get("fingerprint") == session.fingerprint:
            return entry.get("summary") or None
        return None

    def set(self, session: Session, summary: str) -> None:
        self.data[session.session_id] = {
            "summary": summary,
            "fingerprint": session.fingerprint,
        }

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def apply(self, sessions: list[Session]) -> int:
        """Attach cached summaries to sessions. Returns how many were filled."""
        filled = 0
        for s in sessions:
            cached = self.get(s)
            if cached:
                s.summary = cached
                filled += 1
        return filled


def build_prompt(excerpt: str) -> str:
    return (
        "Summarise what this Claude Code session is about in a single concise "
        "phrase of at most 8 words. It should read like a title. Use no quotes "
        "and no trailing punctuation. Reply with only the phrase.\n\n"
        "Transcript:\n" + excerpt
    )


def _clean(text: str) -> str:
    summary = " ".join(text.strip().split())
    summary = summary.strip("\"'").rstrip(".")
    return summary[:_MAX_SUMMARY_CHARS]


def summarize_session(
    session: Session,
    *,
    model: str | None = None,
    claude_bin: str | None = None,
    timeout: float = 60.0,
) -> str:
    """Generate a one-line summary for ``session`` via ``claude -p``.

    Raises :class:`SummaryError` on any failure (missing binary, non-zero exit,
    timeout, empty output).
    """
    cbin = claude_bin or os.environ.get("CLAUDE_MANAGER_CLAUDE_BIN") or "claude"
    excerpt = read_transcript_text(session.path)
    if not excerpt:
        raise SummaryError("transcript is empty")
    argv = [cbin, "-p", "--model", resolve_model(model), "--output-format", "text"]
    try:
        proc = subprocess.run(
            argv,
            input=build_prompt(excerpt),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise SummaryError(f"'{cbin}' not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise SummaryError("timed out") from exc
    except OSError as exc:
        raise SummaryError(str(exc)) from exc
    if proc.returncode != 0:
        msg = (proc.stderr or "").strip() or f"claude exited {proc.returncode}"
        raise SummaryError(msg)
    summary = _clean(proc.stdout)
    if not summary:
        raise SummaryError("empty summary")
    return summary
