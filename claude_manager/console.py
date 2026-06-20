"""Numbered, paginated interactive console for resuming sessions.

Shows the latest sessions with a number on each. Type a number to open that
session in your default terminal (``claude --resume <id>``); use ``n``/``p`` to
page through Next / Previous sets of sessions; ``q`` to quit.

The navigation and dispatch logic (:class:`SessionConsole`) is pure so it can be
unit-tested; :meth:`SessionConsole.run` wraps it in an input loop.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from claude_manager.core import Session
from claude_manager.launch import (
    LaunchError,
    launch_session,
    resolve_terminal,
)
from claude_manager.render import Painter, age_styles, human_age, human_count

DEFAULT_PAGE_SIZE = 10


def _title(session: Session, width: int = 44) -> str:
    text = (session.title or "(no prompt)").replace("\n", " ").strip()
    if len(text) > width:
        text = text[: width - 1] + "…"
    return text


class SessionConsole:
    def __init__(
        self,
        sessions: list[Session],
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        terminal: str | None = None,
        claude_bin: str | None = None,
        color: bool = True,
    ):
        self.sessions = sessions
        self.page_size = max(1, page_size)
        self.terminal = terminal
        self.claude_bin = claude_bin
        self.paint = Painter(color)
        self.page = 0
        self.message = ""
        self.message_style: tuple[str, ...] = ()

    # -- pagination ----------------------------------------------------
    @property
    def total_pages(self) -> int:
        if not self.sessions:
            return 1
        return (len(self.sessions) + self.page_size - 1) // self.page_size

    @property
    def can_next(self) -> bool:
        return self.page < self.total_pages - 1

    @property
    def can_prev(self) -> bool:
        return self.page > 0

    def page_slice(self) -> tuple[int, list[Session]]:
        """Return (start index, sessions) for the current page."""
        start = self.page * self.page_size
        return start, self.sessions[start : start + self.page_size]

    def go_next(self) -> bool:
        if self.can_next:
            self.page += 1
            return True
        return False

    def go_prev(self) -> bool:
        if self.can_prev:
            self.page -= 1
            return True
        return False

    # -- input handling ------------------------------------------------
    def handle(self, raw: str):
        """Map a raw input line to an action tuple.

        Returns one of: ("quit", None), ("open", Session), ("next", None),
        ("prev", None), ("noop", None), ("message", str).
        """
        token = (raw or "").strip().lower()
        if token == "":
            return ("noop", None)
        if token in ("q", "quit", "exit"):
            return ("quit", None)
        if token in ("n", "next", ">"):
            if self.go_next():
                return ("next", None)
            return ("message", "Already on the last page.")
        if token in ("p", "prev", "previous", "<"):
            if self.go_prev():
                return ("prev", None)
            return ("message", "Already on the first page.")
        if token.isdigit():
            idx = int(token)
            if 1 <= idx <= len(self.sessions):
                return ("open", self.sessions[idx - 1])
            return ("message", f"No session #{idx} — pick 1–{len(self.sessions)}.")
        return ("message", f"Unknown command '{raw.strip()}'. Use #, n, p or q.")

    # -- rendering -----------------------------------------------------
    def render(self, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        p = self.paint
        start, page = self.page_slice()
        live = sum(1 for s in self.sessions if s.is_live)
        num_w = len(str(len(self.sessions))) if self.sessions else 1

        out = [
            p("  Claude Code Manager — sessions", "bold", "cyan"),
            p(
                f"  {len(self.sessions)} sessions · "
                f"{p(str(live) + ' live', 'green') if live else '0 live'}"
                f" · page {self.page + 1}/{self.total_pages}",
                "dim",
            ),
            "",
        ]
        if not page:
            out.append(p("  (no sessions)", "dim"))
        for offset, s in enumerate(page):
            number = start + offset + 1
            marker = p("●", "green", "bold") if s.is_live else " "
            age = human_age(s.last_ts, now)
            branch = (s.git_branch or "-")[:16]
            row = (
                f"  {p(f'[{number:>{num_w}}]', 'bold', 'yellow')} "
                f"{marker} "
                f"{p(f'{age:<5}', *age_styles(age))} "
                f"{p(f'{s.project_name[:18]:<18}', 'cyan')} "
                f"{p(f'{branch:<16}', 'magenta')} "
                f"{p(f'{s.short_id:<8}', 'dim')} "
                f"{p(f'{human_count(s.message_count):>4}', 'blue')} "
                f"{p(f'{human_count(s.usage.total):>6}', 'green')}  "
                f"{_title(s)}"
            )
            out.append(row)

        out.append("")
        out.append(self._buttons())
        if self.message:
            out.append("  " + p(self.message, *(self.message_style or ("yellow",))))
        return "\n".join(out)

    def _buttons(self) -> str:
        p = self.paint
        prev = p(" ◀ Prev (p) ", "bold", "black", "bg_white") if self.can_prev \
            else p(" ◀ Prev (p) ", "dim")
        nxt = p(" Next (n) ▶ ", "bold", "black", "bg_white") if self.can_next \
            else p(" Next (n) ▶ ", "dim")
        quit_btn = p(" Quit (q) ", "bold", "white", "bg_red")
        return f"  {prev}  {nxt}    {quit_btn}"

    def prompt(self) -> str:
        return self.paint("  Enter # to resume · n/p to navigate · q to quit › ",
                          "bold")

    # -- actions -------------------------------------------------------
    def open_session(self, session: Session) -> None:
        try:
            launch_session(session, terminal=self.terminal,
                           claude_bin=self.claude_bin)
            term = resolve_terminal(self.terminal)
            self.message = (
                f"▶ Resuming {session.short_id} ({session.project_name}) in {term}…"
            )
            self.message_style = ("green",)
        except LaunchError as exc:
            self.message = str(exc)
            self.message_style = ("red",)

    def run(self, clear: bool | None = None) -> None:
        """Interactive loop. ``clear`` redraws a clean screen each turn."""
        if clear is None:
            clear = sys.stdout.isatty()
        while True:
            if clear:
                sys.stdout.write("\033[2J\033[H")
            print(self.render())
            self.message = ""
            self.message_style = ()
            try:
                raw = input(self.prompt())
            except (EOFError, KeyboardInterrupt):
                print()
                return
            action, payload = self.handle(raw)
            if action == "quit":
                return
            if action == "open":
                self.open_session(payload)
            elif action == "message":
                self.message = payload
                self.message_style = ("yellow",)
