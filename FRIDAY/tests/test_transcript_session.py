from core.audio.transcript_session import TranscriptSession


def test_transcript_session_replaces_prefix_revisions():
    session = TranscriptSession("seg1")
    assert session.revise("hel") == "hel"
    assert session.revise("hello") == "hello"
    assert session.revise("hellhello") == "hello"


def test_transcript_session_does_not_concat_unrelated():
    session = TranscriptSession("seg2")
    assert session.revise("help") == "help"
