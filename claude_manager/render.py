"""Terminal rendering helpers for the overview screen.

Pure stdlib: colours are raw ANSI escapes, gated behind :func:`use_color` so the
output degrades cleanly when piped to a file or a dumb terminal.
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timezone

from claude_manager.core import MemoryFile, Session

_COLORS = {
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
}


def use_color(stream=sys.stdout, override: bool | None = None) -> bool:
    if override is not None:
        return override
    if os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


class Painter:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def __call__(self, text: str, *styles: str) -> str:
        if not self.enabled or not styles:
            return text
        prefix = "".join(_COLORS.get(s, "") for s in styles)
        return f"{prefix}{text}{_COLORS['reset']}"


def terminal_width(default: int = 100) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except OSError:
        return default


def human_age(ts: datetime | None, now: datetime | None = None) -> str:
    """Return a compact relative age such as ``3m``, ``5h`` or ``2d``."""
    if ts is None:
        return "-"
    now = now or datetime.now(timezone.utc)
    seconds = (now - ts).total_seconds()
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    if seconds < 86400 * 30:
        return f"{int(seconds // 86400)}d"
    return ts.strftime("%Y-%m-%d")


def human_dt(ts: datetime | None) -> str:
    if ts is None:
        return "-"
    return ts.astimezone().strftime("%Y-%m-%d %H:%M")


def human_count(n: int) -> str:
    """Abbreviate large integers: 1234 -> 1.2k, 2_500_000 -> 2.5M."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return f"{n / 1_000_000:.1f}M".replace(".0M", "M")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "K", "M"):
        if value < 1024:
            return f"{int(value)}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}G"


def _truncate(text: str, width: int) -> str:
    text = text.replace("\n", " ").strip()
    if width <= 1:
        return text[:width]
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _pad(text: str, width: int) -> str:
    if len(text) >= width:
        return text
    return text + " " * (width - len(text))


def render_overview(
    sessions: list[Session],
    memories: list[MemoryFile],
    *,
    color: bool = False,
    limit: int | None = None,
    now: datetime | None = None,
) -> str:
    paint = Painter(color)
    now = now or datetime.now(timezone.utc)
    width = terminal_width()
    out: list[str] = []

    # --- Header / summary line -------------------------------------------
    projects = {s.project_path for s in sessions if s.project_path}
    live = sum(1 for s in sessions if s.is_live)
    total_tokens = sum(s.usage.total for s in sessions)
    header = paint("Claude Code Manager", "bold", "cyan")
    out.append(header)
    summary = (
        f"{_plural(len(sessions), 'session')}  ·  "
        f"{_plural(len(projects), 'project')}  ·  "
        f"{live} live  ·  {human_count(total_tokens)} tokens  ·  "
        f"{_plural(len(memories), 'memory file')}"
    )
    out.append(paint(summary, "dim"))
    out.append("")

    # --- Sessions table --------------------------------------------------
    out.append(paint("SESSIONS", "bold"))
    shown = sessions if limit is None else sessions[:limit]
    if not shown:
        out.append(paint("  (no sessions found)", "dim"))
    else:
        # Fixed-width columns; the title flexes to fill the terminal.
        cols = [
            ("", 1),          # live marker
            ("AGE", 5),
            ("PROJECT", 16),
            ("BRANCH", 14),
            ("ID", 8),
            ("MSGS", 5),
            ("TOKENS", 7),
        ]
        fixed = sum(w for _, w in cols) + len(cols)  # +1 space between columns
        title_w = max(12, width - fixed - 1)
        head = " ".join(
            _pad(name, w) if name not in ("MSGS", "TOKENS") else _pad(name, w)
            for name, w in cols
        )
        head = f"{head} {_pad('TITLE', title_w)}"
        out.append(paint(head, "dim"))
        for s in shown:
            marker = paint("●", "green") if s.is_live else " "
            age = human_age(s.last_ts, now)
            row = " ".join(
                [
                    marker,
                    _pad(age, 5),
                    _pad(_truncate(s.project_name, 16), 16),
                    _pad(_truncate(s.git_branch or "-", 14), 14),
                    _pad(s.short_id, 8),
                    _pad(human_count(s.message_count), 5),
                    _pad(human_count(s.usage.total), 7),
                    _truncate(s.title or "(no prompt)", title_w),
                ]
            )
            out.append(row)
    if limit is not None and len(sessions) > limit:
        out.append(paint(f"  … {len(sessions) - limit} more (use --all)", "dim"))
    out.append("")

    # --- Memory table ----------------------------------------------------
    out.append(paint("MEMORY", "bold"))
    if not memories:
        out.append(paint("  (no CLAUDE.md memory files found)", "dim"))
    else:
        out.append(paint(f"  {_pad('SCOPE', 8)} {_pad('PROJECT', 16)} "
                         f"{_pad('MODIFIED', 16)} {_pad('SIZE', 6)} {_pad('LINES', 6)} PATH",
                         "dim"))
        for m in memories:
            scope_color = "magenta" if m.scope == "user" else "blue"
            row = (
                f"  {paint(_pad(m.scope, 8), scope_color)} "
                f"{_pad(_truncate(m.project_name, 16), 16)} "
                f"{_pad(human_dt(m.modified), 16)} "
                f"{_pad(human_size(m.size), 6)} "
                f"{_pad(str(m.lines), 6)} "
                f"{paint(_truncate(str(m.path), max(10, width - 60)), 'dim')}"
            )
            out.append(row)

    return "\n".join(out)


def render_session_detail(session: Session, *, color: bool = False) -> str:
    paint = Painter(color)
    out: list[str] = []
    out.append(paint(f"Session {session.session_id}", "bold", "cyan"))
    if session.is_live:
        out.append(paint(f"  ● LIVE (pid {session.live_pid})", "green"))
    rows = [
        ("Project", session.project_path or "(unknown)"),
        ("Branch", session.git_branch or "-"),
        ("Model", session.model or "-"),
        ("Entrypoint", session.entrypoint or "-"),
        ("Version", session.version or "-"),
        ("Messages", str(session.message_count)),
        ("First activity", human_dt(session.first_ts)),
        ("Last activity", human_dt(session.last_ts)),
        ("Started", human_dt(session.started_at) if session.started_at else "-"),
        (
            "Tokens",
            f"{session.usage.total} total "
            f"(in {session.usage.input}, out {session.usage.output}, "
            f"cache {session.usage.cache_read + session.usage.cache_creation})",
        ),
        ("Transcript", str(session.path)),
    ]
    label_w = max(len(label) for label, _ in rows)
    for label, value in rows:
        out.append(f"  {paint(_pad(label, label_w), 'dim')}  {value}")
    if session.title:
        out.append("")
        out.append(paint("  First prompt:", "dim"))
        out.append(f"  {session.title}")
    return "\n".join(out)
