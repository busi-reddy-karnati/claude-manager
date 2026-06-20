"""Interactive, clickable session browser (curses).

Renders the session list in a full-screen view where you can:

* move the selection with the arrow keys (or j/k),
* click a row with the mouse to select it,
* press Enter (or double-click) to open that session in Ghostty,
* press q / Esc to quit.

Opening hands off to :func:`claude_manager.launch.launch_session`, which spawns
a detached terminal running ``claude --resume <id>``.
"""

from __future__ import annotations

import curses
from datetime import datetime, timezone

from claude_manager.core import Session
from claude_manager.launch import LaunchError, launch_session
from claude_manager.render import human_age, human_count


def _fmt_row(session: Session, now: datetime, width: int) -> str:
    live = "*" if session.is_live else " "
    age = human_age(session.last_ts, now)
    project = (session.project_name or "?")[:16].ljust(16)
    branch = (session.git_branch or "-")[:14].ljust(14)
    sid = session.short_id.ljust(8)
    msgs = human_count(session.message_count).ljust(5)
    toks = human_count(session.usage.total).ljust(7)
    prefix = f"{live} {age:<5} {project} {branch} {sid} {msgs} {toks} "
    title = (session.title or "(no prompt)").replace("\n", " ")
    avail = max(4, width - len(prefix) - 1)
    if len(title) > avail:
        title = title[: avail - 1] + "…"
    return (prefix + title)[: width - 1]


class _Browser:
    def __init__(self, sessions: list[Session], terminal: str | None,
                 claude_bin: str | None):
        self.sessions = sessions
        self.terminal = terminal
        self.claude_bin = claude_bin
        self.selected = 0
        self.top = 0  # first visible session index (scroll offset)
        self.status = "↑/↓ move · Enter/click open in terminal · q quit"
        self._colors: dict[str, int] = {}

    def _color(self, name: str) -> int:
        """Return a curses attribute for a colour, or 0 if unsupported."""
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
        }
        for i, (name, fg) in enumerate(palette.items(), start=1):
            try:
                curses.init_pair(i, fg, bg)
                self._colors[name] = curses.color_pair(i)
            except curses.error:
                pass

    # -- geometry ------------------------------------------------------
    HEADER_ROWS = 3   # title + summary + column header
    FOOTER_ROWS = 1   # status line

    def _list_height(self, maxy: int) -> int:
        return max(1, maxy - self.HEADER_ROWS - self.FOOTER_ROWS)

    def _clamp_scroll(self, maxy: int) -> None:
        height = self._list_height(maxy)
        if self.selected < self.top:
            self.top = self.selected
        elif self.selected >= self.top + height:
            self.top = self.selected - height + 1
        self.top = max(0, min(self.top, max(0, len(self.sessions) - height)))

    def _row_to_index(self, y: int, maxy: int) -> int | None:
        """Map a screen row from a mouse click to a session index."""
        first = self.HEADER_ROWS
        height = self._list_height(maxy)
        if first <= y < first + height:
            idx = self.top + (y - first)
            if 0 <= idx < len(self.sessions):
                return idx
        return None

    # -- drawing -------------------------------------------------------
    def draw(self, stdscr) -> None:
        stdscr.erase()
        maxy, maxx = stdscr.getmaxyx()
        now = datetime.now(timezone.utc)
        self._clamp_scroll(maxy)

        live = sum(1 for s in self.sessions if s.is_live)
        title = "Claude Code Manager — sessions"
        summary = f"{len(self.sessions)} sessions · {live} live"
        stdscr.addnstr(0, 0, title, maxx - 1,
                       curses.A_BOLD | self._color("cyan"))
        stdscr.addnstr(1, 0, summary, maxx - 1, curses.A_DIM)
        header = (" " + "AGE".ljust(5) + " " + "PROJECT".ljust(16) + " "
                  + "BRANCH".ljust(14) + " " + "ID".ljust(8) + " "
                  + "MSGS".ljust(5) + " " + "TOKENS".ljust(7) + " TITLE")
        stdscr.addnstr(2, 0, header[: maxx - 1], maxx - 1, curses.A_DIM)

        height = self._list_height(maxy)
        for row in range(height):
            idx = self.top + row
            if idx >= len(self.sessions):
                break
            session = self.sessions[idx]
            text = _fmt_row(session, now, maxx)
            if idx == self.selected:
                attr = curses.A_REVERSE | curses.A_BOLD
            elif session.is_live:
                attr = curses.A_BOLD | self._color("green")
            else:
                attr = self._color("cyan")
            stdscr.addnstr(self.HEADER_ROWS + row, 0, text.ljust(maxx - 1),
                           maxx - 1, attr)

        stdscr.addnstr(maxy - 1, 0, self.status[: maxx - 1].ljust(maxx - 1),
                       maxx - 1, curses.A_REVERSE | self._color("yellow"))
        stdscr.refresh()

    # -- actions -------------------------------------------------------
    def open_selected(self, stdscr) -> None:
        if not self.sessions:
            return
        session = self.sessions[self.selected]
        try:
            launch_session(session, terminal=self.terminal,
                           claude_bin=self.claude_bin)
            self.status = f"Opened {session.short_id} in terminal — {session.project_name}"
        except LaunchError as exc:
            self.status = str(exc)
        curses.flash()

    # -- main loop -----------------------------------------------------
    def run(self, stdscr) -> None:
        curses.curs_set(0)
        self._init_colors()
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        except curses.error:
            pass
        stdscr.keypad(True)

        while True:
            self.draw(stdscr)
            try:
                key = stdscr.getch()
            except KeyboardInterrupt:
                return

            if key in (ord("q"), 27):  # q or Esc
                return
            elif key in (curses.KEY_DOWN, ord("j")):
                self.selected = min(self.selected + 1, max(0, len(self.sessions) - 1))
            elif key in (curses.KEY_UP, ord("k")):
                self.selected = max(self.selected - 1, 0)
            elif key in (curses.KEY_NPAGE,):
                maxy, _ = stdscr.getmaxyx()
                self.selected = min(self.selected + self._list_height(maxy),
                                    max(0, len(self.sessions) - 1))
            elif key in (curses.KEY_PPAGE,):
                maxy, _ = stdscr.getmaxyx()
                self.selected = max(self.selected - self._list_height(maxy), 0)
            elif key in (curses.KEY_HOME,):
                self.selected = 0
            elif key in (curses.KEY_END,):
                self.selected = max(0, len(self.sessions) - 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                self.open_selected(stdscr)
            elif key == curses.KEY_MOUSE:
                self._handle_mouse(stdscr)

    def _handle_mouse(self, stdscr) -> None:
        try:
            _, _mx, my, _, bstate = curses.getmouse()
        except curses.error:
            return
        maxy, _ = stdscr.getmaxyx()
        idx = self._row_to_index(my, maxy)
        if idx is None:
            return
        self.selected = idx
        # A click selects; a click on the already-selected row (or a
        # double-click) opens it. BUTTON1_CLICKED fires on press+release.
        if bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED
                     | curses.BUTTON1_RELEASED):
            self.open_selected(stdscr)


def browse(sessions: list[Session], *, terminal: str | None = None,
           claude_bin: str | None = None) -> None:
    """Run the interactive browser until the user quits."""
    if not sessions:
        print("No sessions to browse.")
        return
    browser = _Browser(sessions, terminal, claude_bin)
    curses.wrapper(browser.run)
