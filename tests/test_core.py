"""Tests for session and memory discovery against a synthetic ~/.claude tree."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_manager.core import (  # noqa: E402
    discover_memory,
    discover_sessions,
    parse_session,
)
from claude_manager.launch import (  # noqa: E402
    LaunchError,
    build_launch_argv,
    launch_session,
)
from claude_manager.render import human_age, human_count, render_overview  # noqa: E402

import pytest  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _make_home(tmp_path: Path) -> Path:
    home = tmp_path / ".claude"
    project_cwd = str(tmp_path / "work" / "proj")
    sess_dir = home / "projects" / "-encoded-proj"
    _write_jsonl(
        sess_dir / "11111111-aaaa-bbbb-cccc-222222222222.jsonl",
        [
            {
                "type": "user",
                "timestamp": "2026-06-20T06:17:18.048Z",
                "cwd": project_cwd,
                "gitBranch": "main",
                "version": "2.1.183",
                "entrypoint": "remote_mobile",
                "origin": {"kind": "human"},
                "message": {"role": "user", "content": "Build me a dashboard please"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-20T06:18:30.000Z",
                "cwd": project_cwd,
                "message": {
                    "role": "assistant",
                    "model": "claude-opus-4-8",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_input_tokens": 10,
                        "cache_creation_input_tokens": 5,
                    },
                },
            },
            {"type": "queue-operation", "timestamp": "2026-06-20T06:19:00.000Z"},
        ],
    )
    # A project CLAUDE.md memory file.
    Path(project_cwd).mkdir(parents=True, exist_ok=True)
    (Path(project_cwd) / "CLAUDE.md").write_text("# rules\nbe nice\n", encoding="utf-8")
    # A user-level memory file.
    (home / "CLAUDE.md").write_text("global\n", encoding="utf-8")
    return home


def test_parse_session_fields(tmp_path):
    home = _make_home(tmp_path)
    sessions = discover_sessions(home)
    assert len(sessions) == 1
    s = sessions[0]
    assert s.short_id == "11111111"
    assert s.git_branch == "main"
    assert s.model == "claude-opus-4-8"
    assert s.title == "Build me a dashboard please"
    assert s.message_count == 2  # user + assistant, not queue-operation
    assert s.usage.total == 165
    assert s.entrypoint == "remote_mobile"
    assert s.first_ts is not None and s.last_ts is not None
    assert s.last_ts > s.first_ts
    assert not s.is_live


def test_memory_discovery(tmp_path):
    home = _make_home(tmp_path)
    sessions = discover_sessions(home)
    mem = discover_memory(home, [s.project_path for s in sessions if s.project_path])
    scopes = sorted(m.scope for m in mem)
    assert scopes == ["project", "user"]
    user = next(m for m in mem if m.scope == "user")
    assert user.project_name == "(user)"


def test_malformed_lines_are_skipped(tmp_path):
    home = tmp_path / ".claude"
    p = home / "projects" / "x" / "33333333-dead-beef-0000-111111111111.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"type":"user"}\nnot json at all\n{bad\n', encoding="utf-8")
    s = parse_session(p)
    assert s.message_count == 1  # only the valid user line counted


def test_render_overview_smoke(tmp_path):
    home = _make_home(tmp_path)
    sessions = discover_sessions(home)
    mem = discover_memory(home, [s.project_path for s in sessions if s.project_path])
    text = render_overview(sessions, mem, color=False)
    assert "SESSIONS" in text
    assert "MEMORY" in text
    assert "Build me a dashboard" in text


def test_humanizers():
    assert human_count(999) == "999"
    assert human_count(1500) == "1.5k"
    assert human_count(2_000_000) == "2M"
    assert human_age(None) == "-"


def test_build_launch_argv_ghostty(tmp_path):
    from claude_manager.core import Session

    s = Session(session_id="abcd-1234", path=tmp_path / "x.jsonl",
                project_path="/home/user/proj")
    argv = build_launch_argv(s, terminal="ghostty", claude_bin="claude")
    assert argv == [
        "ghostty",
        "--working-directory=/home/user/proj",
        "-e",
        "claude",
        "--resume",
        "abcd-1234",
    ]


def test_build_launch_argv_generic_terminal(tmp_path):
    from claude_manager.core import Session

    s = Session(session_id="id1", path=tmp_path / "x.jsonl",
                project_path="/tmp/my proj")
    argv = build_launch_argv(s, terminal="xterm", claude_bin="claude")
    assert argv[0] == "xterm"
    assert argv[1] == "-e"
    # The cwd (with a space) must be safely quoted inside the shell command.
    joined = argv[-1]
    assert "cd '/tmp/my proj'" in joined
    assert "claude --resume id1" in joined


def test_launch_session_missing_terminal_raises(tmp_path):
    from claude_manager.core import Session

    s = Session(session_id="id1", path=tmp_path / "x.jsonl")
    with pytest.raises(LaunchError):
        launch_session(s, terminal="definitely-not-a-real-terminal-xyz")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
