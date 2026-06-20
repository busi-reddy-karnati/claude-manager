"""Launch a Claude Code session in a terminal (Ghostty by default).

Clicking a session in the interactive browser, or running ``claude-manager
open <id>``, opens a fresh terminal window whose shell runs
``claude --resume <sessionId>`` in that session's original working directory --
dropping you straight back into the conversation.

The terminal is configurable so this works beyond Ghostty:

* ``--terminal`` / ``CLAUDE_MANAGER_TERMINAL`` overrides the terminal binary.
* ``--claude-bin`` / ``CLAUDE_MANAGER_CLAUDE_BIN`` overrides the ``claude`` CLI.

Command construction is pure and side-effect free (see :func:`build_launch_argv`)
so it can be unit-tested without a GUI; :func:`launch_session` performs the
actual spawn.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from claude_manager.core import Session

DEFAULT_TERMINAL = "ghostty"
DEFAULT_CLAUDE_BIN = "claude"

# Per-terminal recipes for "open a new window, in this directory, running this
# command". Each entry maps the terminal's basename to a builder that takes the
# working directory and the command argv and returns a full argv list.
#
# Ghostty:  ghostty --working-directory=<cwd> -e claude --resume <id>
# Most xterm-likes accept `-e <cmd>` and we prefix a `cd` via a login shell when
# they have no working-directory flag.


def resolve_terminal(terminal: str | None = None) -> str:
    return terminal or os.environ.get("CLAUDE_MANAGER_TERMINAL") or DEFAULT_TERMINAL


def resolve_claude_bin(claude_bin: str | None = None) -> str:
    return (
        claude_bin
        or os.environ.get("CLAUDE_MANAGER_CLAUDE_BIN")
        or DEFAULT_CLAUDE_BIN
    )


def build_resume_argv(session: Session, claude_bin: str | None = None) -> list[str]:
    """The inner command that resumes the session."""
    return [resolve_claude_bin(claude_bin), "--resume", session.session_id]


def build_launch_argv(
    session: Session,
    *,
    terminal: str | None = None,
    claude_bin: str | None = None,
) -> list[str]:
    """Build the full terminal-launch argv for ``session``.

    Ghostty (and the common case) gets a native ``--working-directory`` flag.
    Other terminals fall back to ``-e <shell> -lc 'cd … && claude --resume …'``
    so the session still starts in the right directory.
    """
    term = resolve_terminal(terminal)
    cbin = resolve_claude_bin(claude_bin)
    cwd = session.project_path or str(Path.home())
    resume = [cbin, "--resume", session.session_id]
    base = os.path.basename(term)

    if base in ("ghostty",):
        return [term, f"--working-directory={cwd}", "-e", *resume]

    # Generic xterm-style fallback: run a login shell that cd's first.
    inner = f"cd {_shquote(cwd)} && exec {' '.join(_shquote(a) for a in resume)}"
    return [term, "-e", "sh", "-lc", inner]


def _shquote(value: str) -> str:
    import shlex

    return shlex.quote(value)


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
    Raises :class:`LaunchError` if the terminal binary cannot be found.
    """
    term = resolve_terminal(terminal)
    argv = build_launch_argv(session, terminal=terminal, claude_bin=claude_bin)
    if dry_run:
        return argv

    if shutil.which(term) is None and not os.path.isabs(term):
        raise LaunchError(
            f"Terminal '{term}' not found on PATH. Install it, or pass "
            f"--terminal <binary> (or set CLAUDE_MANAGER_TERMINAL)."
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
        raise LaunchError(f"Failed to launch '{term}': {exc}") from exc
    return argv
