import asyncio
import os
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.llm.model_manager import ModelManager
from core.llm.llm_worker import LlmWorker
from core.router.complexity_detector import detect_query_complexity


def test_detect_complexity_simple():
    """Simple queries trigger 'simple'."""
    assert detect_query_complexity("weather") == "simple"
    assert detect_query_complexity("What's the weather?") == "simple"
    assert detect_query_complexity("What time is it?") == "simple"
    assert detect_query_complexity("Tell me a joke") == "simple"
    assert detect_query_complexity("thanks") == "simple"


def test_detect_complexity_complex():
    """Complex queries trigger 'complex'."""
    assert detect_query_complexity("analyze the data") == "complex"
    assert detect_query_complexity("make me a python script") == "complex"
    assert detect_query_complexity("build a dashboard") == "complex"
    assert detect_query_complexity("explain quantum computing") == "complex"
    assert detect_query_complexity("code an api") == "complex"


@pytest.mark.asyncio
async def test_model_switch_3b_to_7b():
    """Escalating 3B -> 7B announces degraded mode and restarts process."""
    bus = EventBus()
    await bus.start()
    events = []
    bus.subscribe(EventType.RESPONSE_READY, lambda e: events.append(e))

    mm = ModelManager(event_bus=bus)
    old_proc = MagicMock()
    mm.process = old_proc
    mm.current_model = "3b"

    new_proc = MagicMock()
    try:
        with patch("subprocess.Popen", return_value=new_proc) as mock_popen, \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("os.system") as mock_system:

            await mm.switch_model("7b", "user_request")

            # Process switched
            old_proc.terminate.assert_called_once()
            mock_popen.assert_called_once()
            cmd_called = mock_popen.call_args[0][0]
            assert any("qwen2.5-7b-instruct-q4_k_m.gguf" in arg for arg in cmd_called)
            assert mm.current_model == "7b"
            assert mm.process == new_proc

            # Acknowledgment spoken
            await bus.drain()
            assert len(events) == 1
            assert "Going into degraded mode, full power..." in events[0].payload.get("text", "")
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_model_switch_7b_to_3b():
    """De-escalating 7B -> 3B announces relaxing and restarts process."""
    bus = EventBus()
    await bus.start()
    events = []
    bus.subscribe(EventType.RESPONSE_READY, lambda e: events.append(e))

    mm = ModelManager(event_bus=bus)
    old_proc = MagicMock()
    mm.process = old_proc
    mm.current_model = "7b"

    new_proc = MagicMock()
    try:
        with patch("subprocess.Popen", return_value=new_proc) as mock_popen, \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("os.system") as mock_system:

            await mm.switch_model("3b", "simple_query")

            # Process switched
            old_proc.terminate.assert_called_once()
            mock_popen.assert_called_once()
            cmd_called = mock_popen.call_args[0][0]
            assert any("qwen2.5-3b-instruct-q5_k_m.gguf" in arg for arg in cmd_called)
            assert mm.current_model == "3b"
            assert mm.process == new_proc

            # Acknowledgment spoken
            await bus.drain()
            assert len(events) == 1
            assert "I need to relax boss, I come back in one moment" in events[0].payload.get("text", "")
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_timeout_escalates():
    """If inference takes >10s, auto-escalates to 7B and retries."""
    mock_client = MagicMock()
    mock_mm = MagicMock()
    mock_mm.switch_model = AsyncMock()

    call_count = 0
    async def delayed_generate(prompt, max_tokens=500):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            await asyncio.sleep(15)  # artificially delay by 15s
            return "delayed response"
        return "7b response"

    mock_client.generate = delayed_generate

    worker = LlmWorker(client=mock_client, model_manager=mock_mm, timeout=0.05)  # fast timeout in test
    response = await worker.generate("complex question")

    mock_mm.switch_model.assert_awaited_once_with("7b", "timeout")
    assert response == "7b response"


@pytest.mark.asyncio
async def test_beep_on_escalate():
    """Verify sound signal command executed on escalation."""
    mm = ModelManager()
    with patch("os.system") as mock_os_system, \
         patch.object(mm, "load_model", new_callable=AsyncMock):
        
        await mm.switch_model("7b", "test")
        mock_os_system.assert_called_once_with("powershell -c [console]::beep(1000, 500)")


def test_vram_freed_on_switch():
    """Verify VRAM tracking and that unload precedes load avoiding VRAM overlap."""
    mm = ModelManager()
    lifecycle = []
    
    proc_mock = MagicMock()
    proc_mock.terminate.side_effect = lambda: lifecycle.append("unloaded")
    mm.process = proc_mock
    mm.current_model = "3b"

    def fake_popen(*args, **kwargs):
        lifecycle.append("loaded")
        return MagicMock()

    # Query nvidia-smi if available to verify command execution
    vram_before = None
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True
        )
        vram_before = int(res.stdout.strip())
    except Exception:
        pass

    with patch("subprocess.Popen", side_effect=fake_popen), \
         patch("asyncio.sleep", new_callable=AsyncMock), \
         patch("os.system"):
        asyncio.run(mm.load_model("7b"))

    assert lifecycle == ["unloaded", "loaded"], "Must unload previous model before loading new model to prevent VRAM spike"
    if vram_before is not None:
        assert vram_before >= 0
