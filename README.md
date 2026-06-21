# claude-manager

A single-screen terminal dashboard for your Claude Code **sessions**, **memory**,
and **timestamps** — and a fast way to resume any of them.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/busi-reddy-karnati/claude-manager/main/install.sh | bash
```

Then run:

```bash
claude-manager
```

No dependencies — just Python 3.9+ and the standard library. The installer
downloads the source, builds a single self-contained executable with your local
Python, and installs it to `~/.local/bin`.

<details>
<summary>Other ways to install &amp; run</summary>

```bash
# From a clone — no curl | bash
git clone https://github.com/busi-reddy-karnati/claude-manager
cd claude-manager
make install          # build + copy to ~/.local/bin   (make uninstall to remove)

# Run straight from source, or install as a package
python3 -m claude_manager
pipx install .        # exposes the `claude-manager` command
```

The installer honours `CLAUDE_MANAGER_BIN_DIR` (install location),
`CLAUDE_MANAGER_REF` (branch/tag/commit), and `CLAUDE_MANAGER_REPO`.
</details>

## Uninstall

If you installed with the `curl | bash` one-liner or `make install`, remove the
single executable:

```bash
rm -f ~/.local/bin/claude-manager
```

From a clone you can also run `make uninstall` (add `PREFIX=…` if you installed
somewhere custom). Installed a different way? `pipx uninstall claude-manager`.

That's everything claude-manager itself adds. It never modifies your Claude Code
data — `~/.claude` is left untouched. To also drop the cached AI summaries:

```bash
rm -rf ~/.cache/claude-manager
```

<details>
<summary>Installed somewhere custom?</summary>

If you set `CLAUDE_MANAGER_BIN_DIR` (or `PREFIX`/`BIN_DIR`) when installing,
remove it from there instead — `which claude-manager` shows the path:

```bash
rm -f "$(command -v claude-manager)"
```

Likewise, if you set `XDG_CACHE_HOME`, the summary cache lives at
`$XDG_CACHE_HOME/claude-manager` rather than `~/.cache/claude-manager`.
</details>

## What it does

Claude Code keeps a lot of useful state under `~/.claude` (session transcripts,
live process metadata, `CLAUDE.md` memory files), but it's spread across many
files and not easy to survey at a glance. `claude-manager` reads that state
directly and renders a compact dashboard in your terminal.

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

## Interactive carousel

Running `claude-manager` with no arguments (in a terminal) drops you into the
**carousel** — one session per card, flip through them with a single key press:

```
  Claude Code Manager
  session 2 of 12  ·  1 live

              ╭──────────────────────────────────────────────╮
              │ Fitnesswispr                                  │
              │                                               │
              │ I along with a lot of gym goers need to       │
              │ reconsider their workout plans…               │
              │                                               │
              │ last accessed   38s ago                       │
              │                 2026-06-21 00:07              │
              │ tokens          389.3M                        │
              ╰──────────────────────────────────────────────╯

                              · ● · · · · · · · · · ·
        ←/→  a/d  h/l  n/p   move      ⏎ / space   resume      q   quit
```

Several cards are shown at once (the focused one is highlighted), and each keeps
it simple: a **summary** of what the session was about, **when you last accessed
it**, and its **token** usage.

* **← / →** (or `a`/`d`, `h`/`l`, `n`/`p`) → flip to the previous / next session.
  No Enter required — it moves on the key press, with a quick slide animation.
* **Enter / Space** → resume the focused session in your default terminal
  (`claude --resume <id>`).
* **`s`** → summarise the focused session right now (see below).
* **Home / End** → jump to the first / last session.
* **`q`** → quit.

```bash
claude-manager carousel              # same thing, explicitly
```

### AI summaries

By default a card shows the session's first prompt. For a cleaner one-line
**summary of what the session was actually about**, claude-manager asks Claude —
reusing the `claude` CLI you already have (no API key needed), in non-interactive
mode with a small, fast model. The model is chosen in this order:
`--model` → `CLAUDE_MANAGER_SUMMARY_MODEL` → `ANTHROPIC_SMALL_FAST_MODEL` (the
small model your Claude Code is already configured with) → the `haiku` alias —
so it works out of the box on managed backends like Bedrock, Vertex, or Azure
Foundry without extra setup.

```bash
claude-manager summarize             # summarise all sessions, cache the results
claude-manager summarize --force     # re-summarise everything
claude-manager summarize --model sonnet
```

Summaries are cached at `~/.cache/claude-manager/summaries.json`, keyed so a
session is only re-summarised when it changes. The carousel shows cached
summaries automatically; pressing **`s`** summarises the focused card on the fly.

#### Check your setup works

Summaries shell out to your `claude` CLI, so they automatically use whatever
backend you've configured — the Anthropic API, Amazon Bedrock, Google Vertex, or
a company gateway such as **Microsoft Azure AI Foundry**. Auth, base URL, and
proxy settings are inherited; there's nothing extra to wire up.

Verify it in one command:

```bash
claude -p "say hi" --model haiku
```

If you get a reply, like:

```
Hey! 👋 How can I help you with your code today?
```

then `claude-manager summarize` will work as-is.

#### If it doesn't respond

1. **Make sure plain `claude` works first.** Run `claude -p "say hi"` (no
   `--model`). If *that* fails, it's an auth/login or network issue with Claude
   Code itself — fix that before summaries can work (e.g. `claude` to log in, or
   check your corporate proxy / VPN).

2. **If only the `--model haiku` part errors** (e.g. "model not found"), your
   backend doesn't recognise the `haiku` alias. This is common on
   Bedrock / Vertex / Azure Foundry, where models are addressed by a provider
   model id or a **deployment name**. If your Claude Code already sets
   `ANTHROPIC_SMALL_FAST_MODEL` (managed backends usually do), claude-manager
   picks it up automatically — nothing to do. Otherwise point it at the right
   model explicitly:

   ```bash
   export CLAUDE_MANAGER_SUMMARY_MODEL="<your-model-id-or-deployment-name>"
   # or per-run:
   claude-manager summarize --model "<your-model-id-or-deployment-name>"
   ```

3. **Confirm.** Re-run the check with your model, then summarise one session:

   ```bash
   claude -p "say hi" --model "<your-model>"
   claude-manager summarize --project <a-project-name>
   ```

If summaries still aren't available, the carousel simply falls back to showing
each session's first prompt — everything else keeps working.

Prefer a different style? `claude-manager console` is a numbered, paginated list
(type a number to resume), and `claude-manager browse` is a mouse-clickable
table.

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
