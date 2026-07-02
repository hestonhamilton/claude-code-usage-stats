from pathlib import Path

from cus.parser import parse_file, parse_lines


FIXTURE = Path(__file__).parent / "fixtures" / "project-one" / "session-1.jsonl"


def test_parse_file_extracts_assistant_usage_and_tools():
    result = parse_file(FIXTURE)

    assert result.skipped == 1
    assert len(result.events) == 2
    assert len(result.titles) == 2

    event = result.events[0]
    assert event.uuid == "event-1"
    assert event.session_id == "session-1"
    assert event.ts == "2026-06-16T02:53:44.170Z"
    assert event.model == "claude-opus-4-8"
    assert event.cwd == "/work/project-one"
    assert event.git_branch == "main"
    assert event.is_sidechain is False
    assert event.input_tokens == 100
    assert event.output_tokens == 25
    assert event.cache_creation_tokens == 30
    assert event.cache_read_tokens == 40
    assert event.ephemeral_1h_tokens == 20
    assert event.ephemeral_5m_tokens == 10
    assert event.service_tier == "standard"
    assert event.web_search == 2
    assert event.web_fetch == 1
    assert event.tool_uses == ["Read", "Bash"]


def test_parse_lines_skips_unknown_shapes_without_crashing():
    result = parse_lines(
        [
            '{"type":"assistant","uuid":"missing-required"}',
            '{"type":"ai-title","sessionId":"s1"}',
            '{"type":"mode","sessionId":"s1","mode":"default"}',
            '["not", "an", "object"]',
        ]
    )

    assert result.events == []
    assert result.titles == []
    assert result.skipped == 3
