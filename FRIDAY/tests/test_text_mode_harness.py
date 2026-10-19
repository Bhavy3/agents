from scripts.verify_text_mode import events_for_correlation


def test_live_harness_keeps_only_events_from_the_prompt_turn():
    events = [
        {"event": "STREAM_CHUNK", "correlation_id": "turn-a"},
        {"event": "ACTION_GRAPH_COMPLETED", "correlation_id": "turn-b"},
        {"event": "RESPONSE_READY", "correlation_id": "turn-a"},
    ]

    assert events_for_correlation(events, "turn-a") == [events[0], events[2]]
