"""Command-line interface for claude-manager."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from claude_manager import __version__
from claude_manager.core import (
    Session,
    default_home,
    discover_memory,
    discover_sessions,
)
from claude_manager.launch import LaunchError, build_launch_argv, launch_session
from claude_manager.render import (
    render_overview,
    render_session_detail,
    use_color,
)

DEFAULT_OVERVIEW_LIMIT = 15


def _color_flag(args) -> bool:
    if getattr(args, "no_color", False):
        return False
    if getattr(args, "json", False):
        return False
    return use_color(override=True if getattr(args, "color", False) else None)


def _filter_sessions(sessions: list[Session], project: str | None) -> list[Session]:
    if not project:
        return sessions
    needle = project.lower()
    return [
        s
        for s in sessions
        if (s.project_path and needle in s.project_path.lower())
        or needle in s.project_name.lower()
    ]


def _json_default(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"not serialisable: {type(obj)!r}")


def _session_to_dict(s: Session) -> dict:
    return {
        "session_id": s.session_id,
        "project_path": s.project_path,
        "project_name": s.project_name,
        "title": s.title,
        "git_branch": s.git_branch,
        "model": s.model,
        "entrypoint": s.entrypoint,
        "version": s.version,
        "message_count": s.message_count,
        "first_ts": s.first_ts,
        "last_ts": s.last_ts,
        "started_at": s.started_at,
        "is_live": s.is_live,
        "live_pid": s.live_pid,
        "tokens": asdict(s.usage) | {"total": s.usage.total},
        "path": s.path,
    }


def _memory_to_dict(m) -> dict:
    return {
        "scope": m.scope,
        "project_path": m.project_path,
        "project_name": m.project_name,
        "path": m.path,
        "size": m.size,
        "lines": m.lines,
        "modified": m.modified,
    }


def cmd_overview(args) -> int:
    home = Path(args.home).expanduser() if args.home else default_home()
    sessions = _filter_sessions(discover_sessions(home), args.project)
    memories = discover_memory(
        home, [s.project_path for s in sessions if s.project_path]
    )
    if args.json:
        payload = {
            "home": str(home),
            "generated_at": datetime.now().astimezone(),
            "sessions": [_session_to_dict(s) for s in sessions],
            "memory": [_memory_to_dict(m) for m in memories],
        }
        print(json.dumps(payload, default=_json_default, indent=2))
        return 0
    limit = None if args.all else DEFAULT_OVERVIEW_LIMIT
    print(
        render_overview(
            sessions, memories, color=_color_flag(args), limit=limit
        )
    )
    return 0


def cmd_sessions(args) -> int:
    home = Path(args.home).expanduser() if args.home else default_home()
    sessions = _filter_sessions(discover_sessions(home), args.project)
    if args.json:
        print(json.dumps([_session_to_dict(s) for s in sessions],
                         default=_json_default, indent=2))
        return 0
    memories = []
    print(render_overview(sessions, memories, color=_color_flag(args), limit=None))
    return 0


def _match_sessions(sessions: list[Session], needle: str) -> list[Session]:
    needle = needle.lower()
    return [
        s
        for s in sessions
        if s.session_id.lower() == needle or s.short_id.lower() == needle
        or s.session_id.lower().startswith(needle)
    ]


def _resolve_one(sessions: list[Session], session_id: str) -> Session | None:
    """Return a single matching session, printing a diagnostic otherwise."""
    matches = _match_sessions(sessions, session_id)
    if not matches:
        print(f"No session matching '{session_id}'", file=sys.stderr)
        return None
    if len(matches) > 1:
        print(f"Ambiguous id '{session_id}' matches {len(matches)} sessions:",
              file=sys.stderr)
        for s in matches:
            print(f"  {s.short_id}  {s.project_name}  {s.title[:50]}", file=sys.stderr)
        return None
    return matches[0]


def cmd_show(args) -> int:
    home = Path(args.home).expanduser() if args.home else default_home()
    sessions = discover_sessions(home)
    if args.json:
        matches = _match_sessions(sessions, args.session_id)
        if not matches:
            print(f"No session matching '{args.session_id}'", file=sys.stderr)
            return 1
        print(json.dumps(_session_to_dict(matches[0]), default=_json_default, indent=2))
        return 0
    session = _resolve_one(sessions, args.session_id)
    if session is None:
        return 1
    print(render_session_detail(session, color=_color_flag(args)))
    return 0


def cmd_open(args) -> int:
    home = Path(args.home).expanduser() if args.home else default_home()
    sessions = discover_sessions(home)
    session = _resolve_one(sessions, args.session_id)
    if session is None:
        return 1
    if args.dry_run:
        argv = build_launch_argv(
            session, terminal=args.terminal, claude_bin=args.claude_bin
        )
        print(" ".join(argv))
        return 0
    try:
        argv = launch_session(
            session, terminal=args.terminal, claude_bin=args.claude_bin
        )
    except LaunchError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Opened {session.short_id} ({session.project_name}) — {' '.join(argv)}")
    return 0


def cmd_console(args) -> int:
    from claude_manager.console import SessionConsole

    home = Path(args.home).expanduser() if args.home else default_home()
    sessions = _filter_sessions(discover_sessions(home), args.project)
    if not sessions:
        print("No sessions found.", file=sys.stderr)
        return 1
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("The console needs an interactive terminal (a TTY).", file=sys.stderr)
        return 1
    console = SessionConsole(
        sessions,
        page_size=args.page_size,
        terminal=args.terminal,
        claude_bin=args.claude_bin,
        color=_color_flag(args),
    )
    try:
        console.run()
    except KeyboardInterrupt:
        print()
    return 0


def cmd_browse(args) -> int:
    from claude_manager.browse import browse  # imported lazily (needs a TTY)

    home = Path(args.home).expanduser() if args.home else default_home()
    sessions = _filter_sessions(discover_sessions(home), args.project)
    if not sessions:
        print("No sessions found.", file=sys.stderr)
        return 1
    if not sys.stdout.isatty():
        print("browse requires an interactive terminal (a TTY).", file=sys.stderr)
        return 1
    browse(sessions, terminal=args.terminal, claude_bin=args.claude_bin)
    return 0


def cmd_memory(args) -> int:
    home = Path(args.home).expanduser() if args.home else default_home()
    sessions = discover_sessions(home)
    memories = discover_memory(
        home, [s.project_path for s in sessions if s.project_path]
    )
    if args.json:
        print(json.dumps([_memory_to_dict(m) for m in memories],
                         default=_json_default, indent=2))
        return 0
    print(render_overview([], memories, color=_color_flag(args), limit=0))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-manager",
        description="Single-screen overview of Claude Code sessions and memory.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", help="Claude home dir (default: ~/.claude)")
    common.add_argument("--project", help="Filter by project path / name substring")
    common.add_argument("--json", action="store_true", help="Emit JSON")
    common.add_argument("--color", action="store_true", help="Force ANSI colour")
    common.add_argument("--no-color", action="store_true", help="Disable colour")

    # Options for the commands that launch a terminal.
    launch_opts = argparse.ArgumentParser(add_help=False)
    launch_opts.add_argument(
        "--terminal",
        help="Terminal to open (default: your platform's default terminal; "
        "or set CLAUDE_MANAGER_TERMINAL / TERMINAL)",
    )
    launch_opts.add_argument(
        "--claude-bin", dest="claude_bin",
        help="Path to the claude CLI (default: claude)",
    )

    sub = parser.add_subparsers(dest="command")

    p_con = sub.add_parser(
        "console", parents=[common, launch_opts],
        help="Interactive numbered console — type a # to resume, n/p to page",
    )
    p_con.add_argument("--page-size", type=int, default=10,
                       help="Sessions per page (default: 10)")
    p_con.set_defaults(func=cmd_console)

    p_over = sub.add_parser("overview", parents=[common],
                            help="Dashboard of sessions and memory (default)")
    p_over.add_argument("--all", action="store_true", help="Show every session")
    p_over.set_defaults(func=cmd_overview)

    p_sess = sub.add_parser("sessions", parents=[common], help="List all sessions")
    p_sess.set_defaults(func=cmd_sessions)

    p_show = sub.add_parser("show", parents=[common], help="Detail for one session")
    p_show.add_argument("session_id", help="Full or short session id")
    p_show.set_defaults(func=cmd_show)

    p_browse = sub.add_parser(
        "browse", parents=[common, launch_opts],
        help="Interactive, clickable session list (Enter/click opens Ghostty)",
    )
    p_browse.set_defaults(func=cmd_browse)

    p_open = sub.add_parser(
        "open", parents=[common, launch_opts],
        help="Open one session in a new terminal (claude --resume)",
    )
    p_open.add_argument("session_id", help="Full or short session id")
    p_open.add_argument("--dry-run", action="store_true",
                        help="Print the launch command instead of running it")
    p_open.set_defaults(func=cmd_open)

    p_mem = sub.add_parser("memory", parents=[common], help="List CLAUDE.md memory")
    p_mem.set_defaults(func=cmd_memory)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    # Default to the overview command when none is given.
    known = {"overview", "sessions", "show", "memory", "browse", "open", "console"}
    if not argv:
        # Bare invocation: drop into the interactive console on a TTY,
        # otherwise print the static overview (e.g. when piped).
        argv = ["console"] if sys.stdin.isatty() and sys.stdout.isatty() \
            else ["overview"]
    elif argv[0] not in known and argv[0] not in ("-h", "--help", "--version"):
        argv = ["overview"] + argv
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(args)
