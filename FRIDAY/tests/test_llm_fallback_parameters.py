import logging
import pytest
from core.router.llm_fallback import _extract_parameters


def test_1_exact_log_string_ending_in_parenthesis():
    raw = '{"intent": "search_web", "confidence": 0.9, "suggested_action": "", "reasoning_summary": "User is asking about the weather.", "parameters": {"query": "current weather"})'
    assert _extract_parameters(raw) == {"query": "current weather"}


def test_2_valid_json_with_parameters():
    raw = '{"intent": "search_web", "confidence": 0.9, "parameters": {"query": "current weather"}}'
    assert _extract_parameters(raw) == {"query": "current weather"}


def test_3_valid_json_without_parameters():
    raw = '{"intent": "chat", "confidence": 0.95, "suggested_action": ""}'
    assert _extract_parameters(raw) == {}


def test_4_truncated_outer_closing_brace_missing():
    raw = '{"intent": "search_web", "confidence": 0.9, "parameters": {"query": "current weather"}'
    assert _extract_parameters(raw) == {"query": "current weather"}


def test_5_garbage_text_logs_error(caplog):
    with caplog.at_level(logging.ERROR):
        result = _extract_parameters("this is completely non-json garbage text")
    assert result == {}
    assert any(
        record.levelname == "ERROR" and record.message == "llm_parameters_unrecoverable"
        for record in caplog.records
    )


def test_6_empty_string_expected_error(caplog):
    with caplog.at_level(logging.ERROR):
        result = _extract_parameters("")
    assert result == {}
    assert any(
        record.levelname == "ERROR" and record.message == "llm_parameters_unrecoverable"
        for record in caplog.records
    )


def test_7_markdown_fenced_json():
    raw = '```json\n{"intent": "search_web", "parameters": {"query": "current weather"}}\n```'
    assert _extract_parameters(raw) == {"query": "current weather"}


def test_8_trailing_whitespace_and_newlines_after_parenthesis():
    raw = '{"intent": "search_web", "parameters": {"query": "current weather"})\n\n   '
    assert _extract_parameters(raw) == {"query": "current weather"}


def test_9_query_containing_internal_braces():
    raw = '{"intent": "search_web", "parameters": {"query": "what does {x: 1} mean?"}'
    assert _extract_parameters(raw) == {"query": "what does {x: 1} mean?"}


def test_10_unicode_query():
    raw = '{"intent": "search_web", "parameters": {"query": "café München 20°C"}}'
    assert _extract_parameters(raw) == {"query": "café München 20°C"}


def test_11_parameters_null_returns_empty_dict():
    raw = '{"intent": "search_web", "confidence": 0.9, "parameters": null}'
    assert _extract_parameters(raw) == {}
