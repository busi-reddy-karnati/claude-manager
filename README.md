# claude-manager

A single-screen overview of your Claude Code **sessions**, **memory**, and
**timestamps** — all in one place.

Claude Code keeps a lot of useful state under `~/.claude` (session transcripts,
live process metadata, `CLAUDE.md` memory files), but it's spread across many
files and not easy to survey at a glance. `claude-manager` reads that state
directly and renders a compact dashboard in your terminal.

It has **no dependencies** — just Python 3.10+ and the standard library.

## Quick start

```bash
# Run straight from the repo (no install needed)
python3 -m claude_manager

# …or install it to get the `claude-manager` command
pip install -e .
claude-manager
```

## What you see

```
Claude Code Manager
3 sessions  ·  2 projects  ·  1 live  ·  950.4k tokens  ·  2 memory files

SESSIONS
  AGE   PROJECT          BRANCH         ID       MSGS  TOKENS  TITLE
● 0s    claude-manager   claude/sess…   dfe79c6e 57    950.4k  I want to use claude code…
  3h    my-api           main           a1b2c3d4 24    120.0k  Fix the failing auth test
  2d    notes            -              99887766 8     12.0k   Summarise these meeting notes

MEMORY
  SCOPE    PROJECT          MODIFIED          SIZE   LINES  PATH
  user     (user)           2026-06-19 11:02  1.2K   40     /root/.claude/CLAUDE.md
  project  my-api           2026-06-18 09:14  640B   22     /home/user/my-api/CLAUDE.md
```

* A green `●` marks **live** sessions (a Claude Code process is still running).
* `AGE` is the time since the last activity in that session.
* `TOKENS` is the cumulative token usage (input + output + cache) for the session.

## Interactive console (numbered, paginated)

Running `claude-manager` with no arguments (in a terminal) drops you into the
**interactive console** — a numbered, colourful, paginated list of your latest
sessions:

```
  Claude Code Manager — sessions
  47 sessions · 1 live · page 1/5

  [ 1] ● 0s    claude-manager     main             dfe79c6e  213   7.5M  Build a session manager…
  [ 2]   3h    my-api             feat/login       a1b2c3d4   24   120k  Fix the failing auth test
  [ 3]   2d    notes              -                99887766    8    12k  Summarise meeting notes
  …

   ◀ Prev (p)    Next (n) ▶     Quit (q)
  Enter # to resume · n/p to navigate · q to quit ›
```

* **Type a number** → opens that session in your terminal, resuming it
  (`claude --resume <id>`). Numbering is global, so you can type any number.
* **`n` / `p`** → Next / Previous page.
* **`q`** → quit.

```bash
claude-manager console               # same thing, explicitly
claude-manager console --page-size 20
```

There's also a mouse-driven curses view — `claude-manager browse` — where you
**click a row** (or press Enter) to open it.

## Open in your default terminal

Sessions open in your platform's **default terminal**, resuming
`claude --resume <id>` in the session's original directory:

* **macOS** → Terminal.app (via `osascript`)
* **Linux** → `$TERMINAL`, else the Debian `x-terminal-emulator` default, else
  the first known terminal on `PATH` (gnome-terminal, konsole, kitty, alacritty,
  wezterm, xterm, …)

Open a specific session from the command line:

```bash
claude-manager open dfe79c6e            # open in the default terminal
claude-manager open dfe79c6e --dry-run  # just print the command
```

Override the terminal anytime:

```bash
claude-manager open dfe79c6e --terminal kitty
export CLAUDE_MANAGER_TERMINAL=ghostty   # or set it once
```

## Commands

| Command | Description |
| --- | --- |
| `claude-manager` / `console` | Interactive numbered console (default in a TTY). Type a # to resume, `n`/`p` to page. |
| `claude-manager overview` | Static dashboard of sessions + memory. Add `--all` to list every session. |
| `claude-manager browse` | Mouse-clickable curses list — click/Enter opens the session. |
| `claude-manager open <id>` | Open one session in your default terminal (`claude --resume`). `--dry-run` to preview. |
| `claude-manager sessions` | Full session list (no truncation). |
| `claude-manager show <id>` | Detailed view of one session (full or short id). |
| `claude-manager memory` | List all `CLAUDE.md` memory files with timestamps. |

### Options

* `--project <text>` — filter to projects whose path/name contains `<text>`.
* `--json` — emit machine-readable JSON instead of the table (great for scripting).
* `--home <dir>` — point at a non-default Claude home (also honours `CLAUDE_CONFIG_DIR`).
* `--color` / `--no-color` — force or disable ANSI colour (auto-detected by default).
* `--terminal <bin>` / `--claude-bin <bin>` — (for `browse`/`open`) override the
  terminal or the `claude` CLI used to launch sessions.

## Where the data comes from

| Source | Path | Used for |
| --- | --- | --- |
| Session transcripts | `~/.claude/projects/<cwd>/<id>.jsonl` | titles, timestamps, message counts, model, tokens, branch |
| Live process metadata | `~/.claude/sessions/<pid>.json` | live `●` marker, start time |
| User memory | `~/.claude/CLAUDE.md` | user-scoped memory |
| Project memory | `<project>/CLAUDE.md`, `<project>/.claude/CLAUDE.md` | project-scoped memory |

## Development

```bash
pip install pytest
python3 -m pytest tests/ -q
```

## License

MIT
