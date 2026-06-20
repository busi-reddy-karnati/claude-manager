"""Launch a Claude Code session in the user's default terminal.

Selecting a session (in the console or via ``claude-manager open <id>``) opens a
new terminal window whose shell runs ``claude --resume <sessionId>`` in that
session's original working directory.

By default we open the platform's **default terminal**:

* macOS  -> Terminal.app (driven via ``osascript``).
* Linux  -> ``$TERMINAL`` if set, else the Debian ``x-terminal-emulator``
  alternative, else the first known terminal found on ``PATH``.

It stays configurable:

* ``--terminal`` / ``CLAUDE_MANAGER_TERMINAL`` overrides the terminal.
* ``--claude-bin`` / ``CLAUDE_MANAGER_CLAUDE_BIN`` overrides the ``claude`` CLI.

Command construction (:func:`build_launch_argv`) is pure and unit-testable;
:func:`launch_session` performs the actual spawn.
"""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
from pathlib import Path

from claude_manager.core import Session

DEFAULT_CLAUDE_BIN = "claude"

# Linux terminals tried, in order, when no terminal is configured. The Debian
# "x-terminal-emulator" alternative points at whatever the user set as default.
_LINUX_TERMINALS = (
    "x-terminal-emulator",
    "gnome-terminal",
    "konsole",
    "xfce4-terminal",
    "tilix",
    "alacritty",
    "kitty",
    "wezterm",
    "ghostty",
    "xterm",
)


def detect_default_terminal() -> str:
    """Return the platform's default terminal identifier (no env lookups)."""
    system = platform.system()
    if system == "Darwin":
        return "Terminal"  # Terminal.app, launched via osascript.
    for candidate in _LINUX_TERMINALS:
        if shutil.which(candidate):
            return candidate
    return "xterm"


def resolve_terminal(terminal: str | None = None) -> str:
    if terminal:
        return terminal
    env = os.environ.get("CLAUDE_MANAGER_TERMINAL") or os.environ.get("TERMINAL")
    if env:
        return env
    return detect_default_terminal()


def resolve_claude_bin(claude_bin: str | None = None) -> str:
    return (
        claude_bin
        or os.environ.get("CLAUDE_MANAGER_CLAUDE_BIN")
        or DEFAULT_CLAUDE_BIN
    )


def _osascript_escape(value: str) -> str:
    """Escape a string for embedding inside an AppleScript double-quoted literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _shell_command(cwd: str, resume: list[str]) -> str:
    """A POSIX-shell one-liner that cd's into ``cwd`` then execs ``resume``."""
    quoted = " ".join(shlex.quote(a) for a in resume)
    return f"cd {shlex.quote(cwd)} && exec {quoted}"


def build_launch_argv(
    session: Session,
    *,
    terminal: str | None = None,
    claude_bin: str | None = None,
) -> list[str]:
    """Build the full argv that opens ``session`` in a terminal.

    Each terminal family gets a recipe that (a) starts in the session's working
    directory and (b) runs ``claude --resume <id>``. Unknown terminals fall back
    to the widely-supported ``-e sh -lc 'cd … && claude …'`` form.
    """
    term = resolve_terminal(terminal)
    cbin = resolve_claude_bin(claude_bin)
    cwd = session.project_path or str(Path.home())
    resume = [cbin, "--resume", session.session_id]
    base = os.path.basename(term)

    # macOS Terminal.app / iTerm via AppleScript.
    if base in ("Terminal", "Terminal.app", "iTerm", "iTerm.app", "iTerm2"):
        app = "iTerm" if "iterm" in base.lower() else "Terminal"
        script = _osascript_escape(_shell_command(cwd, resume))
        return [
            "osascript",
            "-e", f'tell application "{app}" to activate',
            "-e", f'tell application "{app}" to do script "{script}"',
        ]
    if base == "ghostty":
        return [term, f"--working-directory={cwd}", "-e", *resume]
    if base == "gnome-terminal":
        # Modern gnome-terminal uses `--` to delimit the command.
        return [term, f"--working-directory={cwd}", "--", *resume]
    if base == "konsole":
        return [term, "--workdir", cwd, "-e", *resume]
    if base == "xfce4-terminal":
        return [term, f"--working-directory={cwd}", "-x", *resume]
    if base == "tilix":
        return [term, "--working-directory", cwd, "-e",
                " ".join(shlex.quote(a) for a in resume)]
    if base == "kitty":
        return [term, "--directory", cwd, *resume]
    if base == "alacritty":
        return [term, "--working-directory", cwd, "-e", *resume]
    if base == "wezterm":
        return [term, "start", "--cwd", cwd, "--", *resume]

    # Generic xterm-style (x-terminal-emulator, xterm, urxvt, st, …).
    return [term, "-e", "sh", "-lc", _shell_command(cwd, resume)]


class LaunchError(RuntimeError):
    """Raised when a session cannot be launched (e.g. terminal not installed)."""


def launch_session(
    session: Session,
    *,
    terminal: str | None = None,
    claude_bin: str | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Spawn a detached terminal running the resumed session.

    Returns the argv that was (or would be, for ``dry_run``) executed.
    Raises :class:`LaunchError` if the launcher binary cannot be found.
    """
    argv = build_launch_argv(session, terminal=terminal, claude_bin=claude_bin)
    if dry_run:
        return argv

    exe = argv[0]
    if shutil.which(exe) is None and not os.path.isabs(exe):
        term = resolve_terminal(terminal)
        raise LaunchError(
            f"Terminal '{term}' (launcher '{exe}') not found on PATH. Install it, "
            f"or pass --terminal <binary> (or set CLAUDE_MANAGER_TERMINAL)."
        )

    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # detach so it outlives this process
        )
    except (OSError, ValueError) as exc:  # pragma: no cover - env dependent
        raise LaunchError(f"Failed to launch '{exe}': {exc}") from exc
    return argv
