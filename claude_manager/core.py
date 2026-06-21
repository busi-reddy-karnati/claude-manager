"""Discovery and parsing of Claude Code session and memory data.

Claude Code stores its state under a home directory (``~/.claude`` by default):

* ``projects/<encoded-cwd>/<sessionId>.jsonl`` -- the full transcript of each
  session, one JSON object per line. Lines carry timestamps, the working
  directory, the git branch, the model and per-message token usage.
* ``sessions/<pid>.json`` -- metadata written while a session process is live
  (pid, sessionId, cwd, startedAt). Used here to flag running sessions.
* ``CLAUDE.md`` files -- "memory". One user-level file lives at
  ``~/.claude/CLAUDE.md``; project-level files live in each project tree.

This module turns that on-disk state into plain dataclasses so the CLI and any
other consumer can render or serialise it without re-parsing the files.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Top-level JSONL "type" values that represent an actual conversation turn.
# Everything else (queue-operation, attachment, *-delta, listings) is internal
# bookkeeping and is ignored when counting messages.
_MESSAGE_TYPES = {"user", "assistant"}

# Memory file names searched for inside a project tree, in priority order.
_PROJECT_MEMORY_NAMES = (
    "CLAUDE.md",
    "CLAUDE.local.md",
    os.path.join(".claude", "CLAUDE.md"),
)


def default_home() -> Path:
    """Return the Claude Code home directory, honouring ``CLAUDE_CONFIG_DIR``."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".claude"


def _parse_ts(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp string into an aware UTC datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        # JSONL timestamps look like "2026-06-20T06:17:18.048Z".
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iter_jsonl(path: Path):
    """Yield parsed JSON objects from a JSONL file, skipping malformed lines."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


def _text_from_content(content: object) -> str:
    """Flatten a message ``content`` (string or list of blocks) into text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def _clean_title(text: str) -> str:
    """Reduce a raw first-prompt into a compact single-line title."""
    text = text.strip()
    # Drop local-command / caveat wrappers that Claude Code injects.
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        low = stripped.lower()
        if stripped.startswith("<") and stripped.endswith(">"):
            continue
        if low.startswith("caveat:") or "local-command" in low:
            continue
        lines.append(stripped)
    return " ".join(lines).strip()


@dataclass
class TokenUsage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_creation: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_creation

    def add(self, usage: dict) -> None:
        self.input += int(usage.get("input_tokens") or 0)
        self.output += int(usage.get("output_tokens") or 0)
        self.cache_read += int(usage.get("cache_read_input_tokens") or 0)
        self.cache_creation += int(usage.get("cache_creation_input_tokens") or 0)


@dataclass
class Session:
    session_id: str
    path: Path
    project_path: str | None = None
    title: str = ""
    git_branch: str | None = None
    model: str | None = None
    entrypoint: str | None = None
    version: str | None = None
    message_count: int = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    # Populated from sessions/<pid>.json when the process is still alive.
    live_pid: int | None = None
    started_at: datetime | None = None
    # Optional LLM-generated summary (see claude_manager.summarize); falls back
    # to ``title`` when absent.
    summary: str | None = None

    @property
    def display_summary(self) -> str:
        return self.summary or self.title

    @property
    def fingerprint(self) -> str:
        """Cheap identity of the session's content, for cache invalidation."""
        last = self.last_ts.isoformat() if self.last_ts else ""
        return f"{self.message_count}:{last}"

    @property
    def short_id(self) -> str:
        return self.session_id.split("-")[0]

    @property
    def project_name(self) -> str:
        if not self.project_path:
            return "(unknown)"
        return os.path.basename(self.project_path.rstrip("/")) or self.project_path

    @property
    def is_live(self) -> bool:
        return self.live_pid is not None


@dataclass
class MemoryFile:
    path: Path
    scope: str  # "user" or "project"
    project_path: str | None = None
    size: int = 0
    lines: int = 0
    modified: datetime | None = None

    @property
    def project_name(self) -> str:
        if self.scope == "user":
            return "(user)"
        if not self.project_path:
            return "(unknown)"
        return os.path.basename(self.project_path.rstrip("/")) or self.project_path


def parse_session(path: Path) -> Session:
    """Parse one ``<sessionId>.jsonl`` transcript into a :class:`Session`."""
    session = Session(session_id=path.stem, path=path)
    for obj in _iter_jsonl(path):
        obj_type = obj.get("type")
        ts = _parse_ts(obj.get("timestamp"))
        if ts is not None:
            if session.first_ts is None or ts < session.first_ts:
                session.first_ts = ts
            if session.last_ts is None or ts > session.last_ts:
                session.last_ts = ts

        # Capture per-session context from any line that carries it.
        if session.project_path is None and isinstance(obj.get("cwd"), str):
            session.project_path = obj["cwd"]
        if session.git_branch is None and obj.get("gitBranch"):
            session.git_branch = obj["gitBranch"]
        if session.entrypoint is None and obj.get("entrypoint"):
            session.entrypoint = obj["entrypoint"]
        if session.version is None and obj.get("version"):
            session.version = obj["version"]

        if obj_type not in _MESSAGE_TYPES:
            continue
        session.message_count += 1
        message = obj.get("message")
        if not isinstance(message, dict):
            continue

        if obj_type == "assistant":
            model = message.get("model")
            if model and model != "<synthetic>" and not session.model:
                session.model = model
            usage = message.get("usage")
            if isinstance(usage, dict):
                session.usage.add(usage)
        elif obj_type == "user" and not session.title:
            human = obj.get("origin", {}).get("kind") if isinstance(
                obj.get("origin"), dict
            ) else None
            text = _clean_title(_text_from_content(message.get("content")))
            # Prefer a genuine human prompt, but fall back to any first text.
            if text and (human in (None, "human")):
                session.title = text

    return session


def read_transcript_text(
    path: Path, max_chars: int = 6000, per_message_chars: int = 600
) -> str:
    """Return a representative text excerpt of a session for summarising.

    Reads the whole transcript (each message capped at ``per_message_chars`` so
    one long message can't dominate) and, if it exceeds ``max_chars``, samples
    from the **head and the tail** — the opening usually states the goal, the
    tail shows where the work actually went — dropping the middle. This gives a
    summary of the whole conversation rather than just the first prompt.
    """
    messages: list[str] = []
    for obj in _iter_jsonl(path):
        if obj.get("type") not in _MESSAGE_TYPES:
            continue
        message = obj.get("message")
        if not isinstance(message, dict):
            continue
        text = _text_from_content(message.get("content")).strip()
        if not text:
            continue
        messages.append(f"{obj['type']}: {text[:per_message_chars]}")

    if not messages:
        return ""
    joined = "\n".join(messages)
    if len(joined) <= max_chars:
        return joined

    head_budget = max_chars * 2 // 3
    tail_budget = max_chars - head_budget

    def _take(seq, budget):
        out, used = [], 0
        for m in seq:
            if used + len(m) + 1 > budget:
                break
            out.append(m)
            used += len(m) + 1
        return out

    head = _take(messages, head_budget)
    tail = _take(reversed(messages), tail_budget)
    tail.reverse()
    # Avoid overlap when head and tail meet in the middle.
    tail = [m for m in tail if m not in head]
    return "\n".join(head + ["… (middle of the conversation omitted) …"] + tail)


def _load_live_sessions(home: Path) -> dict[str, dict]:
    """Map sessionId -> live metadata for processes that are still running."""
    live: dict[str, dict] = {}
    sessions_dir = home / "sessions"
    if not sessions_dir.is_dir():
        return live
    for meta_path in sessions_dir.glob("*.json"):
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        session_id = data.get("sessionId")
        pid = data.get("pid")
        if not session_id or not isinstance(pid, int):
            continue
        if _pid_alive(pid):
            live[session_id] = data
    return live


def _pid_alive(pid: int) -> bool:
    """Best-effort check whether a process id is currently running."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Exists but owned by another user.
    except OSError:
        return False
    return True


def discover_sessions(home: Path | None = None) -> list[Session]:
    """Return all sessions found under ``home``, newest activity first."""
    home = home or default_home()
    projects_dir = home / "projects"
    sessions: list[Session] = []
    if projects_dir.is_dir():
        for jsonl in projects_dir.glob("*/*.jsonl"):
            sessions.append(parse_session(jsonl))

    live = _load_live_sessions(home)
    for session in sessions:
        meta = live.get(session.session_id)
        if meta:
            session.live_pid = meta.get("pid")
            started = meta.get("startedAt")
            if isinstance(started, (int, float)):
                session.started_at = datetime.fromtimestamp(
                    started / 1000, tz=timezone.utc
                )

    sessions.sort(
        key=lambda s: s.last_ts or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return sessions


def _read_memory_file(path: Path, scope: str, project_path: str | None) -> MemoryFile:
    try:
        stat = path.stat()
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        return MemoryFile(
            path=path,
            scope=scope,
            project_path=project_path,
            size=stat.st_size,
            lines=lines,
            modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        )
    except OSError:
        return MemoryFile(path=path, scope=scope, project_path=project_path)


def discover_memory(
    home: Path | None = None, project_paths: list[str] | None = None
) -> list[MemoryFile]:
    """Return user-level and project-level CLAUDE.md memory files.

    ``project_paths`` is typically the set of cwds gathered from sessions, so
    memory is reported for exactly the projects the user has worked in.
    """
    home = home or default_home()
    memories: list[MemoryFile] = []

    user_memory = home / "CLAUDE.md"
    if user_memory.is_file():
        memories.append(_read_memory_file(user_memory, "user", None))

    seen: set[Path] = set()
    for raw in sorted(set(project_paths or [])):
        project = Path(raw)
        for name in _PROJECT_MEMORY_NAMES:
            candidate = project / name
            if candidate.is_file() and candidate not in seen:
                seen.add(candidate)
                memories.append(_read_memory_file(candidate, "project", raw))

    memories.sort(
        key=lambda m: m.modified or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return memories
