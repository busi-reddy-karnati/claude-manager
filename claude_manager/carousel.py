"""A carousel of session cards, navigated with single key presses.

One session is shown as a large centered card, with its neighbours peeking in
from the sides. Flip between them with the arrow keys (or a/d, h/l, n/p) — no
Enter needed — and press Enter/Space to resume the focused session in your
default terminal. ``q`` quits.

Each card is deliberately minimal:

  1. a one-line summary of what the session is about,
  2. when it was last accessed,
  3. how many tokens it used.

The pure helpers (:func:`step_index`, :func:`wrap_text`, :func:`card_lines`) are
unit-tested; :class:`Carousel` wraps them in a curses loop with a short slide
animation between cards.
"""

from __future__ import annotations

import curses
from datetime import datetime, timezone

from claude_manager.core import Session
from claude_manager.launch import LaunchError, launch_session, resolve_terminal
from claude_manager.render import human_age, human_count, human_dt

# Navigation key sets (single press, no Enter).
_PREV_KEYS = {curses.KEY_LEFT, ord("a"), ord("h"), ord("p"), ord("A"), ord("H"),
              ord("P")}
_NEXT_KEYS = {curses.KEY_RIGHT, ord("d"), ord("l"), ord("n"), ord("D"), ord("L"),
              ord("N")}
_OPEN_KEYS = {curses.KEY_ENTER, 10, 13, ord(" "), ord("o"), ord("O")}
_QUIT_KEYS = {ord("q"), ord("Q"), 27}

_ANIM_FRAMES = 5
_ANIM_DELAY_MS = 14


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
            if cur:  # don't emit a blank line for an over-long single word
                lines.append(cur)
            cur = w
            if len(lines) >= max_lines:
                truncated = True
                break
    if not truncated:
        if cur:
            lines.append(cur)
        # A single word longer than the whole box still overflows.
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
    """Build the plain-text inner lines of a session card (no colour, no border).

    Layout: project · summary (3 lines) · last accessed · tokens.
    """
    now = now or datetime.now(timezone.utc)
    iw = max(10, inner_width)
    summary = wrap_text(session.title or "(no prompt)", iw, 3)
    age = human_age(session.last_ts, now)
    when = human_dt(session.last_ts)
    lines = [
        ("● LIVE" if session.is_live else session.project_name)[:iw],
        "",
        summary[0],
        summary[1],
        summary[2],
        "",
        f"last accessed   {age} ago"[:iw],
        f"                {when}"[:iw],
        f"tokens          {human_count(session.usage.total)}"[:iw],
    ]
    return lines


class Carousel:
    CARD_MIN_W = 28
    CARD_MAX_W = 64

    def __init__(self, sessions: list[Session], *, terminal: str | None = None,
                 claude_bin: str | None = None):
        self.sessions = sessions
        self.terminal = terminal
        self.claude_bin = claude_bin
        self.index = 0
        self.status = ""
        self._colors: dict[str, int] = {}

    # -- colour ----------------------------------------------------------
    def _color(self, name: str) -> int:
        return self._colors.get(name, 0)

    def _init_colors(self) -> None:
        if not curses.has_colors():
            return
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except curses.error:
            bg = curses.COLOR_BLACK
        palette = {
            "cyan": curses.COLOR_CYAN,
            "green": curses.COLOR_GREEN,
            "yellow": curses.COLOR_YELLOW,
            "magenta": curses.COLOR_MAGENTA,
            "blue": curses.COLOR_BLUE,
            "white": curses.COLOR_WHITE,
        }
        for i, (name, fg) in enumerate(palette.items(), start=1):
            try:
                curses.init_pair(i, fg, bg)
                self._colors[name] = curses.color_pair(i)
            except curses.error:
                pass

    # -- geometry --------------------------------------------------------
    def _card_width(self, maxx: int) -> int:
        return max(self.CARD_MIN_W, min(self.CARD_MAX_W, maxx - 6))

    def _card_rows(self, session: Session, focused: bool, width: int,
                   now: datetime):
        """Return a list of (text, attr) rows for one card, each ``width`` wide."""
        iw = width - 4
        inner = card_lines(session, iw, now)
        if focused:
            border = self._color("green") | curses.A_BOLD if session.is_live \
                else self._color("cyan") | curses.A_BOLD
            line_attrs = [
                (self._color("green") | curses.A_BOLD) if session.is_live
                else (self._color("cyan") | curses.A_BOLD),  # project / LIVE
                0,
                curses.A_BOLD, curses.A_BOLD, curses.A_BOLD,  # summary
                0,
                self._color("yellow"),                         # last accessed
                self._color("yellow") | curses.A_DIM,
                self._color("green") | curses.A_BOLD,          # tokens
            ]
        else:
            border = curses.A_DIM
            line_attrs = [curses.A_DIM] * len(inner)

        rows = [("╭" + "─" * (width - 2) + "╮", border)]
        for text, attr in zip(inner, line_attrs):
            body = "│ " + text.ljust(iw) + " │"
            rows.append((body, attr if focused else curses.A_DIM))
        rows.append(("╰" + "─" * (width - 2) + "╯", border))
        return rows

    # -- drawing ---------------------------------------------------------
    def _put(self, stdscr, y: int, x: int, text: str, attr: int, maxx: int,
             maxy: int) -> None:
        if y < 0 or y >= maxy or not text:
            return
        if x < 0:  # clip the left side (for cards peeking off-screen)
            text = text[-x:]
            x = 0
        if x >= maxx:
            return
        text = text[: maxx - x]
        if not text:
            return
        try:
            stdscr.addstr(y, x, text, attr)
        except curses.error:
            pass  # writing the bottom-right cell raises; ignore.

    def _render(self, stdscr, scroll: float) -> None:
        stdscr.erase()
        maxy, maxx = stdscr.getmaxyx()
        now = datetime.now(timezone.utc)
        n = len(self.sessions)
        focus = int(round(scroll)) % n if n else 0

        # Header.
        live = sum(1 for s in self.sessions if s.is_live)
        self._put(stdscr, 0, 2, "Claude Code Manager", curses.A_BOLD
                  | self._color("cyan"), maxx, maxy)
        sub = f"session {focus + 1} of {n}  ·  {live} live"
        self._put(stdscr, 1, 2, sub, curses.A_DIM, maxx, maxy)

        # Filmstrip of cards.
        width = self._card_width(maxx)
        step = width + 4
        sample = self._card_rows(self.sessions[0], True, width, now)
        card_h = len(sample)
        top = max(3, (maxy - card_h) // 2 - 1)
        center = maxx // 2
        for i, session in enumerate(self.sessions):
            x = center + int(round((i - scroll) * step)) - width // 2
            if x + width < 0 or x > maxx:
                continue
            focused = (i == focus)
            rows = self._card_rows(session, focused, width, now)
            for r, (text, attr) in enumerate(rows):
                y = top + r
                if y >= maxy - 3:  # leave room for the footer
                    break
                self._put(stdscr, y, x, text, attr, maxx, maxy)

        self._draw_footer(stdscr, maxx, maxy, focus, n)
        stdscr.refresh()

    def _draw_footer(self, stdscr, maxx: int, maxy: int, focus: int, n: int) -> None:
        # Position indicator: dots for small N, "i / n" otherwise.
        if n <= 12:
            dots = " ".join("●" if i == focus else "·" for i in range(n))
        else:
            dots = f"‹ {focus + 1} / {n} ›"
        self._put(stdscr, maxy - 3, max(2, (maxx - len(dots)) // 2), dots,
                  self._color("cyan"), maxx, maxy)

        controls = "←/→  a/d  h/l  n/p   move      ⏎ / space   resume      q   quit"
        if self.status:
            controls = self.status
        attr = (self._color("green") if self.status else curses.A_DIM)
        self._put(stdscr, maxy - 1, max(2, (maxx - len(controls)) // 2),
                  controls, attr | curses.A_BOLD, maxx, maxy)

    # -- navigation / actions -------------------------------------------
    def _move(self, stdscr, delta: int) -> None:
        n = len(self.sessions)
        if n <= 1:
            return
        old = self.index
        new = step_index(old, delta, n)
        self.status = ""
        # Animate a single neighbouring step; wrap-around jumps instantly.
        if (delta == 1 and new == old + 1) or (delta == -1 and new == old - 1):
            for f in range(1, _ANIM_FRAMES + 1):
                t = f / _ANIM_FRAMES
                eased = old + (new - old) * (t * t * (3 - 2 * t))  # smoothstep
                self._render(stdscr, eased)
                curses.napms(_ANIM_DELAY_MS)
        self.index = new
        self._render(stdscr, float(new))

    def _open(self, stdscr) -> None:
        session = self.sessions[self.index]
        try:
            launch_session(session, terminal=self.terminal,
                           claude_bin=self.claude_bin)
            term = resolve_terminal(self.terminal)
            self.status = f"▶ Resuming {session.short_id} in {term}…"
        except LaunchError as exc:
            self.status = str(exc)
        curses.flash()
        self._render(stdscr, float(self.index))

    def run(self, stdscr) -> None:
        curses.curs_set(0)
        self._init_colors()
        stdscr.keypad(True)
        self._render(stdscr, float(self.index))
        while True:
            try:
                key = stdscr.getch()
            except KeyboardInterrupt:
                return
            if key in _QUIT_KEYS:
                return
            elif key in _PREV_KEYS:
                self._move(stdscr, -1)
            elif key in _NEXT_KEYS:
                self._move(stdscr, +1)
            elif key in (curses.KEY_HOME,):
                self.index = 0
                self.status = ""
                self._render(stdscr, 0.0)
            elif key in (curses.KEY_END,):
                self.index = len(self.sessions) - 1
                self.status = ""
                self._render(stdscr, float(self.index))
            elif key in _OPEN_KEYS:
                self._open(stdscr)
            elif key == curses.KEY_RESIZE:
                self._render(stdscr, float(self.index))


def carousel(sessions: list[Session], *, terminal: str | None = None,
             claude_bin: str | None = None) -> None:
    """Run the interactive carousel until the user quits."""
    if not sessions:
        print("No sessions to show.")
        return
    curses.wrapper(Carousel(sessions, terminal=terminal,
                            claude_bin=claude_bin).run)
