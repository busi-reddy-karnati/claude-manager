"""A compact, inline session carousel.

Unlike a full-screen TUI, this draws only a small fixed-height block where the
cursor already is (think ``fzf --height``) and updates it in place — so it stays
small and elegant and never blanks the whole terminal.

Navigate with single key presses (no Enter): ← / → (also a/d, h/l, n/p) flip
between sessions, Enter/Space resumes the focused one, ``s`` re-summarises it,
``q`` quits.

Summaries are generated in the background: cards render immediately with any
summary that already exists (from the on-disk cache) and the rest fill in as the
worker finishes them. A generated summary is cached keyed by the session's
content fingerprint, so an unchanged session is never summarised twice.

The pure helpers (:func:`step_index`, :func:`wrap_text`, :func:`card_lines`) are
unit-tested; :class:`InlineCarousel` wraps them in a tiny raw-mode input loop.
"""

from __future__ import annotations

import os
import select
import sys
import threading
from datetime import datetime, timezone

from claude_manager.core import Session
from claude_manager.launch import LaunchError, launch_session, resolve_terminal
from claude_manager.render import Painter, human_age, human_count, human_dt

try:  # POSIX only; carousel() reports a friendly error if missing.
    import termios
    import tty
    _HAVE_TERMIOS = True
except ImportError:  # pragma: no cover - non-POSIX
    _HAVE_TERMIOS = False

CARD_INNER_LINES = 5      # header + 2 summary + time + tokens
CARD_HEIGHT = CARD_INNER_LINES + 2   # + top/bottom border
GAP = 3                   # columns between cards
_POLL_SECONDS = 0.15


def step_index(index: int, delta: int, count: int) -> int:
    """Move ``index`` by ``delta`` within ``count`` items, wrapping around."""
    if count <= 0:
        return 0
    return (index + delta) % count


def wrap_text(text: str, width: int, max_lines: int) -> list[str]:
    """Word-wrap ``text`` to ``width`` columns, padded to exactly ``max_lines``."""
    text = (text or "").replace("\n", " ").strip()
    words = text.split()
    lines: list[str] = []
    cur = ""
    truncated = False
    for w in words:
        candidate = w if not cur else f"{cur} {w}"
        if len(candidate) <= width:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(lines) >= max_lines:
                truncated = True
                break
    if not truncated:
        if cur:
            lines.append(cur)
        truncated = len(lines) > max_lines or (
            bool(words) and any(len(ln) > width for ln in lines)
        )
    lines = lines[:max_lines]
    if truncated and lines:
        last = lines[-1]
        if len(last) > width - 1:
            last = last[: width - 1].rstrip()
        lines[-1] = (last + "…")[:width]
    while len(lines) < max_lines:
        lines.append("")
    return [ln[:width] for ln in lines]


def card_lines(session: Session, inner_width: int, now: datetime | None = None) -> list[str]:
    """Plain-text inner lines of a card: project, summary (2 lines), when, tokens."""
    now = now or datetime.now(timezone.utc)
    iw = max(8, inner_width)
    summary = wrap_text(session.display_summary or "(no prompt)", iw, 2)
    age = human_age(session.last_ts, now)
    header = (("● " if session.is_live else "") + session.project_name)[:iw]
    return [
        header,
        summary[0],
        summary[1],
        f"{age} ago · {human_dt(session.last_ts)}"[:iw],
        f"{human_count(session.usage.total)} tokens"[:iw],
    ]


class InlineCarousel:
    def __init__(self, sessions: list[Session], *, terminal: str | None = None,
                 claude_bin: str | None = None, cache=None,
                 summary_model: str | None = None, color: bool | None = None):
        self.sessions = sessions
        self.terminal = terminal
        self.claude_bin = claude_bin
        self.cache = cache
        self.summary_model = summary_model
        if color is None:
            color = sys.stdout.isatty()
        self.paint = Painter(color)
        self.index = 0
        self.status = ""
        self._rendered = False
        self._height = 0
        self._stop = threading.Event()
        self._dirty = threading.Event()
        self._thread: threading.Thread | None = None

    # -- geometry --------------------------------------------------------
    def _card_width(self, cols: int) -> int:
        return max(26, min(38, (cols - 12) // 3))

    def _visible(self, cols: int, width: int) -> int:
        n = len(self.sessions)
        if n >= 3 and cols >= 3 * width + 2 * GAP + 2:
            return 3
        return 1

    # -- card rendering --------------------------------------------------
    def _card(self, session: Session, focused: bool, width: int,
              now: datetime) -> list[str]:
        iw = width - 4
        inner = card_lines(session, iw, now)
        p = self.paint
        if focused:
            accent = "green" if session.is_live else "cyan"
            attrs = [(accent, "bold"), ("bold",), ("bold",), ("dim",),
                     ("green",)]
            border = (accent, "bold")
        else:
            attrs = [("dim",)] * CARD_INNER_LINES
            border = ("dim",)
        rows = [p("╭" + "─" * (width - 2) + "╮", *border)]
        for text, attr in zip(inner, attrs):
            rows.append(p("│ " + text.ljust(iw) + " │", *attr))
        rows.append(p("╰" + "─" * (width - 2) + "╯", *border))
        return rows

    # -- frame -----------------------------------------------------------
    def _frame(self, cols: int) -> list[str]:
        n = len(self.sessions)
        i = self.index
        width = self._card_width(cols)
        visible = self._visible(cols, width)
        if visible == 3:
            idxs = [(i - 1) % n, i, (i + 1) % n]
            focus_pos = 1
        else:
            idxs = [i]
            focus_pos = 0
        now = datetime.now(timezone.utc)
        cards = [self._card(self.sessions[k], pos == focus_pos, width, now)
                 for pos, k in enumerate(idxs)]
        strip_w = len(idxs) * width + (len(idxs) - 1) * GAP
        pad = " " * max(0, (cols - strip_w) // 2)
        strip = [pad + (" " * GAP).join(card[r] for card in cards)
                 for r in range(CARD_HEIGHT)]

        live = sum(1 for s in self.sessions if s.is_live)
        header_plain = f"Claude Code Manager   ·   session {i + 1}/{n} · {live} live"
        header = (self._lpad(header_plain, cols)
                  + self.paint("Claude Code Manager", "bold", "cyan")
                  + self.paint(f"   ·   session {i + 1}/{n} · {live} live", "dim"))

        if n <= 12:
            dots_plain = " ".join("●" if k == i else "·" for k in range(n))
        else:
            dots_plain = f"‹ {i + 1}/{n} ›"
        dots = self._lpad(dots_plain, cols) + self.paint(dots_plain, "cyan")

        if self.status:
            ctrl_plain = self.status
            ctrl = self._lpad(ctrl_plain, cols) + self.paint(ctrl_plain, "green", "bold")
        else:
            ctrl_plain = "←/→ move   ⏎ resume   s summarise   q quit"
            ctrl = self._lpad(ctrl_plain, cols) + self.paint(ctrl_plain, "dim")

        return [header, *strip, dots, ctrl]

    @staticmethod
    def _lpad(plain: str, cols: int) -> str:
        return " " * max(0, (cols - len(plain)) // 2)

    def _terminal_cols(self) -> int:
        import shutil
        return shutil.get_terminal_size((90, 24)).columns

    def _render(self) -> None:
        lines = self._frame(self._terminal_cols())
        buf = []
        if self._rendered:
            buf.append(f"\033[{self._height}A")
        for line in lines:
            buf.append("\r\033[2K")
            buf.append(line)
            buf.append("\r\n")
        sys.stdout.write("".join(buf))
        sys.stdout.flush()
        self._rendered = True
        self._height = len(lines)

    # -- background summaries -------------------------------------------
    def _worker(self) -> None:
        from claude_manager.summarize import SummaryError, summarize_session

        for s in self.sessions:
            if self._stop.is_set():
                return
            if s.summary:
                continue
            if self.cache is not None:
                cached = self.cache.get(s)
                if cached:
                    s.summary = cached
                    self._dirty.set()
                    continue
            try:
                summary = summarize_session(
                    s, model=self.summary_model, claude_bin=self.claude_bin
                )
            except SummaryError:
                continue
            if self._stop.is_set():
                return
            s.summary = summary
            if self.cache is not None:
                self.cache.set(s, summary)
                self.cache.save()
            self._dirty.set()

    # -- actions ---------------------------------------------------------
    def _move(self, delta: int) -> None:
        self.index = step_index(self.index, delta, len(self.sessions))
        self.status = ""
        self._render()

    def _open(self) -> None:
        session = self.sessions[self.index]
        try:
            launch_session(session, terminal=self.terminal,
                           claude_bin=self.claude_bin)
            self.status = f"▶ resuming {session.short_id} in {resolve_terminal(self.terminal)}"
        except LaunchError as exc:
            self.status = str(exc)
        self._render()

    def _summarize_current(self) -> None:
        from claude_manager.summarize import SummaryError, summarize_session

        session = self.sessions[self.index]
        self.status = f"summarising {session.short_id}…"
        self._render()
        try:
            summary = summarize_session(
                session, model=self.summary_model, claude_bin=self.claude_bin
            )
        except SummaryError as exc:
            self.status = f"summary failed: {exc}"
            self._render()
            return
        session.summary = summary
        if self.cache is not None:
            self.cache.set(session, summary)
            self.cache.save()
        self.status = "✓ summarised"
        self._render()

    # -- input -----------------------------------------------------------
    def _read_key(self, fd: int) -> str | None:
        try:
            data = os.read(fd, 16)
        except OSError:
            return None
        if not data:
            return None
        if data[0] == 0x1b:
            if len(data) == 1:
                return "esc"
            if data[1:2] == b"[":
                return {
                    b"C": "right", b"D": "left", b"A": "left", b"B": "right",
                    b"H": "home", b"F": "end",
                }.get(data[2:3])
            return "esc"
        if data[0] == 3:  # Ctrl-C
            return "q"
        ch = chr(data[0]).lower()
        if ch == "q":
            return "q"
        if ch in ("a", "h", "p"):
            return "left"
        if ch in ("d", "l", "n"):
            return "right"
        if ch == "s":
            return "summarise"
        if ch in ("\r", "\n", " "):
            return "open"
        return None

    def run(self) -> None:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        sys.stdout.write("\n")  # a little breathing room above the widget
        try:
            tty.setcbreak(fd)
            sys.stdout.write("\033[?25l")  # hide cursor
            sys.stdout.flush()
            self._render()
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()
            while True:
                try:
                    ready, _, _ = select.select([sys.stdin], [], [], _POLL_SECONDS)
                except (OSError, ValueError):
                    break
                if ready:
                    key = self._read_key(fd)
                    if key in ("q", "esc"):
                        break
                    elif key == "left":
                        self._move(-1)
                    elif key == "right":
                        self._move(1)
                    elif key == "home":
                        self.index = 0
                        self.status = ""
                        self._render()
                    elif key == "end":
                        self.index = len(self.sessions) - 1
                        self.status = ""
                        self._render()
                    elif key == "open":
                        self._open()
                    elif key == "summarise":
                        self._summarize_current()
                if self._dirty.is_set():
                    self._dirty.clear()
                    self._render()
        finally:
            self._stop.set()
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            sys.stdout.write("\033[?25h\r\n")  # show cursor, move below widget
            sys.stdout.flush()


def carousel(sessions: list[Session], *, terminal: str | None = None,
             claude_bin: str | None = None, cache=None,
             summary_model: str | None = None) -> None:
    """Run the inline carousel until the user quits."""
    if not sessions:
        print("No sessions to show.")
        return
    if not _HAVE_TERMIOS or not sys.stdin.isatty():
        print("The carousel needs an interactive POSIX terminal.")
        return
    InlineCarousel(sessions, terminal=terminal, claude_bin=claude_bin,
                   cache=cache, summary_model=summary_model).run()
