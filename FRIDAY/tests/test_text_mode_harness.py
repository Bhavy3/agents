from scripts import verify_text_mode
from scripts.verify_text_mode import completion_outcome, events_for_correlation


def test_live_harness_keeps_only_events_from_the_prompt_turn():
    events = [
        {"event": "STREAM_CHUNK", "correlation_id": "turn-a"},
        {"event": "ACTION_GRAPH_COMPLETED", "correlation_id": "turn-b"},
        {"event": "RESPONSE_READY", "correlation_id": "turn-a"},
    ]

    assert events_for_correlation(events, "turn-a") == [events[0], events[2]]


def test_live_harness_counts_successful_workflow_graph_as_completion():
    events = [{"event": "ACTION_GRAPH_COMPLETED"}]

    assert completion_outcome(events) == "completed"


def test_live_harness_counts_direct_tool_response_as_completion():
    events = [{"event": "RESPONSE_READY"}]

    assert completion_outcome(events) == "completed"


def test_live_harness_prefers_workflow_failure_over_partial_completion():
    events = [
        {"event": "ASSISTANT_RESPONSE_COMPLETED"},
        {"event": "ACTION_GRAPH_FAILED"},
    ]

    assert completion_outcome(events) == "workflow_failed"


def test_harness_isolates_workflow_store_with_audit_memory_copy(monkeypatch, tmp_path):
    source = tmp_path / "source.db"
    source.write_bytes(b"test-db")
    monkeypatch.setattr(verify_text_mode, "DEFAULT_MEMORY_DB", source)
    monkeypatch.delenv("FRIDAY_WORKFLOW_STORE_PATH", raising=False)

    verify_text_mode.prepare_memory_copy(tmp_path / "audit")

    assert verify_text_mode.os.environ["FRIDAY_WORKFLOW_STORE_PATH"] == str(
        tmp_path / "audit" / "data" / "workflows" / "active_workflows.json"
    )
