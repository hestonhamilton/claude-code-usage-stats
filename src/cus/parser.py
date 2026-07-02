from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import AssistantEvent, ParseResult, TitleRecord


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _title_from_record(record: dict[str, object]) -> str | None:
    for key in ("title", "content", "text", "name"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    message = record.get("message")
    if isinstance(message, dict):
        for key in ("title", "content", "text"):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _parse_assistant(record: dict[str, object]) -> AssistantEvent | None:
    uuid = _as_str(record.get("uuid"))
    session_id = _as_str(record.get("sessionId"))
    ts = _as_str(record.get("timestamp"))
    message = record.get("message")
    if not uuid or not session_id or not ts or not isinstance(message, dict):
        return None

    usage = message.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    cache_creation = usage.get("cache_creation")
    if not isinstance(cache_creation, dict):
        cache_creation = {}
    server_tool_use = usage.get("server_tool_use")
    if not isinstance(server_tool_use, dict):
        server_tool_use = {}

    tool_uses: list[str] = []
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                name = block.get("name")
                if isinstance(name, str) and name:
                    tool_uses.append(name)

    return AssistantEvent(
        uuid=uuid,
        message_id=_as_str(message.get("id")),
        session_id=session_id,
        ts=ts,
        record_type="assistant",
        model=_as_str(message.get("model")),
        cwd=_as_str(record.get("cwd")),
        git_branch=_as_str(record.get("gitBranch")),
        is_sidechain=bool(record.get("isSidechain")) if isinstance(record.get("isSidechain"), bool) else False,
        input_tokens=_as_int(usage.get("input_tokens")),
        output_tokens=_as_int(usage.get("output_tokens")),
        cache_creation_tokens=_as_int(usage.get("cache_creation_input_tokens")),
        cache_read_tokens=_as_int(usage.get("cache_read_input_tokens")),
        ephemeral_1h_tokens=_as_int(cache_creation.get("ephemeral_1h_input_tokens")),
        ephemeral_5m_tokens=_as_int(cache_creation.get("ephemeral_5m_input_tokens")),
        service_tier=_as_str(usage.get("service_tier")),
        web_search=_as_int(server_tool_use.get("web_search_requests")),
        web_fetch=_as_int(server_tool_use.get("web_fetch_requests")),
        tool_uses=tool_uses,
    )


def _parse_title(record: dict[str, object]) -> TitleRecord | None:
    session_id = _as_str(record.get("sessionId"))
    title = _title_from_record(record)
    if not session_id or not title:
        return None
    return TitleRecord(
        session_id=session_id,
        title=title,
        ts=_as_str(record.get("timestamp")),
    )


def parse_lines(iterable_of_str: Iterable[str]) -> ParseResult:
    events: list[AssistantEvent] = []
    titles: list[TitleRecord] = []
    skipped = 0

    for line in iterable_of_str:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(record, dict):
            skipped += 1
            continue

        record_type = record.get("type")
        if record_type == "assistant":
            event = _parse_assistant(record)
            if event is None:
                skipped += 1
            else:
                events.append(event)
        elif record_type in {"ai-title", "custom-title"}:
            title = _parse_title(record)
            if title is None:
                skipped += 1
            else:
                titles.append(title)

    return ParseResult(events=events, titles=titles, skipped=skipped)


def parse_file(path: str | Path, start_offset: int = 0) -> ParseResult:
    file_path = Path(path)
    with file_path.open("rb") as handle:
        handle.seek(start_offset)
        data = handle.read()
    text = data.decode("utf-8", errors="replace")
    result = parse_lines(text.splitlines())
    return ParseResult(
        events=result.events,
        titles=result.titles,
        skipped=result.skipped,
        bytes_read=len(data),
    )
