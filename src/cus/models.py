from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AssistantEvent:
    uuid: str
    message_id: str | None
    session_id: str
    ts: str
    record_type: str
    model: str | None
    cwd: str | None
    git_branch: str | None
    is_sidechain: bool
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    ephemeral_1h_tokens: int
    ephemeral_5m_tokens: int
    service_tier: str | None
    web_search: int
    web_fetch: int
    tool_uses: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TitleRecord:
    session_id: str
    title: str
    ts: str | None = None


@dataclass(frozen=True)
class ParseResult:
    events: list[AssistantEvent]
    titles: list[TitleRecord]
    skipped: int
    bytes_read: int = 0
