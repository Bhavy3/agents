import logging
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from core.audio.pipecat_worker import PipecatAudioWorker


@pytest.mark.asyncio
async def test_audio_device_selection_logged_at_warning(caplog):
    bus_mock = MagicMock()
    bus_mock.publish = AsyncMock()
    worker = PipecatAudioWorker(bus_mock)

    with patch("pyaudio.PyAudio", side_effect=RuntimeError("device enumeration error")), \
         patch("core.audio.pipecat_worker.LocalAudioTransport", side_effect=RuntimeError("stop_after_device_selection")):
        with caplog.at_level(logging.DEBUG):
            try:
                await worker.work()
            except RuntimeError as e:
                if str(e) != "stop_after_device_selection":
                    raise

    records = [
        r for r in caplog.records
        if (r.msg == "audio_device_selection_skipped" or r.getMessage() == "audio_device_selection_skipped")
    ]
    assert len(records) == 1
    assert records[0].levelname == "WARNING"
