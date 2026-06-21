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


def test_build_launch_argv_macos_terminal(tmp_path):
    from claude_manager.core import Session

    s = Session(session_id="id1", path=tmp_path / "x.jsonl", project_path="/w")
    argv = build_launch_argv(s, terminal="Terminal", claude_bin="claude")
    assert argv[0] == "osascript"
    joined = " ".join(argv)
    assert "Terminal" in joined and "do script" in joined
    assert "claude --resume id1" in joined


def test_build_launch_argv_gnome_and_kitty(tmp_path):
    from claude_manager.core import Session

    s = Session(session_id="id1", path=tmp_path / "x.jsonl", project_path="/w")
    gnome = build_launch_argv(s, terminal="gnome-terminal", claude_bin="claude")
    assert gnome == ["gnome-terminal", "--working-directory=/w", "--",
                     "claude", "--resume", "id1"]
    kitty = build_launch_argv(s, terminal="kitty", claude_bin="claude")
    assert kitty == ["kitty", "--directory", "/w", "claude", "--resume", "id1"]


def _make_sessions(n):
    from claude_manager.core import Session

    return [Session(session_id=f"id{i:03d}", path=Path(f"/tmp/{i}.jsonl"),
                    project_path=f"/p/{i}", title=f"task {i}") for i in range(n)]


def test_console_pagination():
    from claude_manager.console import SessionConsole

    c = SessionConsole(_make_sessions(25), page_size=10, color=False)
    assert c.total_pages == 3
    assert c.can_prev is False and c.can_next is True
    start, page = c.page_slice()
    assert start == 0 and len(page) == 10
    assert c.handle("n") == ("next", None)
    assert c.page == 1
    assert c.handle("p") == ("prev", None)
    assert c.page == 0
    # Paging past the ends is reported, not silently wrapped.
    assert c.handle("p")[0] == "message"
    c.page = 2
    assert c.handle("n")[0] == "message"


def test_console_select_by_number():
    from claude_manager.console import SessionConsole

    sessions = _make_sessions(25)
    c = SessionConsole(sessions, page_size=10, color=False)
    action, payload = c.handle("13")
    assert action == "open" and payload is sessions[12]
    # Global numbering works even when off the current page.
    assert c.page == 0
    assert c.handle("0")[0] == "message"
    assert c.handle("99")[0] == "message"
    assert c.handle("q") == ("quit", None)
    assert c.handle("") == ("noop", None)


def test_console_render_has_numbers_and_buttons():
    from claude_manager.console import SessionConsole

    c = SessionConsole(_make_sessions(3), page_size=10, color=False)
    text = c.render()
    assert "[1]" in text and "[3]" in text
    assert "Prev" in text and "Next" in text and "Quit" in text


def test_carousel_step_index_wraps():
    from claude_manager.carousel import step_index

    assert step_index(0, 1, 4) == 1
    assert step_index(3, 1, 4) == 0      # wrap forward off the end
    assert step_index(0, -1, 4) == 3     # wrap backward off the start
    assert step_index(0, 1, 0) == 0      # empty is safe


def test_carousel_wrap_text_pads_and_truncates():
    from claude_manager.carousel import wrap_text

    out = wrap_text("hello world", 20, 3)
    assert len(out) == 3
    assert out[0] == "hello world" and out[1] == "" and out[2] == ""
    long = wrap_text("one two three four five six seven eight nine ten", 10, 2)
    assert len(long) == 2
    assert any("…" in ln for ln in long)  # overflow is marked


def test_carousel_card_shows_summary_age_tokens():
    from claude_manager.core import Session, TokenUsage
    from claude_manager.carousel import card_lines
    from datetime import datetime, timezone

    s = Session(session_id="abc-1", path=Path("/tmp/a.jsonl"),
                project_path="/p/proj", title="Backup my zsh config",
                last_ts=datetime(2026, 6, 21, tzinfo=timezone.utc),
                usage=TokenUsage(input=1_000_000, output=300_000))
    text = "\n".join(card_lines(s, 40))
    assert "Backup my zsh config" in text
    assert "last" in text
    assert "tokens" in text
    assert "1.3M" in text  # token total, humanised


def test_card_prefers_summary_over_title():
    from claude_manager.core import Session
    from claude_manager.carousel import card_lines

    s = Session(session_id="x", path=Path("/tmp/x.jsonl"),
                title="raw first prompt that is long", summary="Tidy summary")
    text = "\n".join(card_lines(s, 40))
    assert "Tidy summary" in text
    assert "raw first prompt" not in text


def test_summary_cache_roundtrip_and_fingerprint(tmp_path):
    from claude_manager.core import Session
    from claude_manager.summarize import SummaryCache
    from datetime import datetime, timezone

    s = Session(session_id="sess-1", path=tmp_path / "s.jsonl",
                message_count=4,
                last_ts=datetime(2026, 6, 21, tzinfo=timezone.utc))
    cache = SummaryCache(path=tmp_path / "summaries.json")
    assert cache.get(s) is None
    cache.set(s, "A neat summary")
    cache.save()

    reloaded = SummaryCache(path=tmp_path / "summaries.json")
    assert reloaded.get(s) == "A neat summary"
    assert reloaded.apply([s]) == 1 and s.summary == "A neat summary"

    # Changing the session content invalidates the cached summary.
    s.message_count = 5
    assert reloaded.get(s) is None


def test_resolve_model_precedence(monkeypatch):
    from claude_manager.summarize import resolve_model

    monkeypatch.delenv("CLAUDE_MANAGER_SUMMARY_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_SMALL_FAST_MODEL", raising=False)
    assert resolve_model() == "haiku"                       # default

    monkeypatch.setenv("ANTHROPIC_SMALL_FAST_MODEL", "azure-haiku-deploy")
    assert resolve_model() == "azure-haiku-deploy"          # Claude Code's small model

    monkeypatch.setenv("CLAUDE_MANAGER_SUMMARY_MODEL", "my-pick")
    assert resolve_model() == "my-pick"                     # our env wins over it

    assert resolve_model("explicit") == "explicit"          # explicit arg wins over all


def test_summary_prompt_and_excerpt(tmp_path):
    from claude_manager.core import read_transcript_text
    from claude_manager.summarize import build_prompt

    path = tmp_path / "t.jsonl"
    _write_jsonl(path, [
        {"type": "user", "message": {"role": "user", "content": "Fix the auth bug"}},
        {"type": "assistant",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "Sure, looking now"}]}},
        {"type": "queue-operation"},
    ])
    excerpt = read_transcript_text(path)
    assert "user: Fix the auth bug" in excerpt
    assert "assistant: Sure, looking now" in excerpt
    assert "queue-operation" not in excerpt
    prompt = build_prompt(excerpt)
    assert "single concise phrase" in prompt and "Fix the auth bug" in prompt


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
