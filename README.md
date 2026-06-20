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

## Open a session (click → Ghostty)

`claude-manager browse` opens an **interactive, clickable** list. Move with the
arrow keys (or `j`/`k`) and **click a row** — or press **Enter** — to open that
session in a new [Ghostty](https://ghostty.org) window running
`claude --resume <id>` in the session's original directory. Press `q` to quit.

```bash
claude-manager browse
```

You can also open a specific session straight from the command line:

```bash
claude-manager open dfe79c6e            # open in Ghostty
claude-manager open dfe79c6e --dry-run  # just print the command
```

Not on Ghostty? Point it at any terminal — Ghostty gets a native
`--working-directory`; other terminals are launched as
`<term> -e sh -lc 'cd <cwd> && claude --resume <id>'`:

```bash
claude-manager open dfe79c6e --terminal kitty
export CLAUDE_MANAGER_TERMINAL=wezterm   # or set it once
```

## Commands

| Command | Description |
| --- | --- |
| `claude-manager` / `overview` | Dashboard of sessions + memory (default). Add `--all` to list every session. |
| `claude-manager browse` | Interactive, clickable session list — Enter/click opens the session in Ghostty. |
| `claude-manager open <id>` | Open one session in a new terminal (`claude --resume`). `--dry-run` to preview. |
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
