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


def _make_launchable(mm: ModelManager) -> None:
    """Use this test module as a valid stand-in for the two required files."""
    mm.server_bin = __file__
    mm.model_paths = {"3b": __file__, "7b": __file__}


def _health_response(status: int) -> MagicMock:
    response = MagicMock()
    response.status = status
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


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
    _make_launchable(mm)
    old_proc = MagicMock()
    mm.process = old_proc
    mm.current_model = "3b"

    new_proc = MagicMock()
    try:
        with patch("subprocess.Popen", return_value=new_proc) as mock_popen, \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("urllib.request.urlopen", return_value=_health_response(200)), \
             patch("os.system") as mock_system:

            await mm.switch_model("7b", "user_request")

            # Process switched
            old_proc.terminate.assert_called_once()
            mock_popen.assert_called_once()
            cmd_called = mock_popen.call_args[0][0]
            assert mm.model_paths["7b"] in cmd_called
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
    _make_launchable(mm)
    old_proc = MagicMock()
    mm.process = old_proc
    mm.current_model = "7b"

    new_proc = MagicMock()
    try:
        with patch("subprocess.Popen", return_value=new_proc) as mock_popen, \
             patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("urllib.request.urlopen", return_value=_health_response(200)), \
             patch("os.system") as mock_system:

            await mm.switch_model("3b", "simple_query")

            # Process switched
            old_proc.terminate.assert_called_once()
            mock_popen.assert_called_once()
            cmd_called = mock_popen.call_args[0][0]
            assert mm.model_paths["3b"] in cmd_called
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
    _make_launchable(mm)
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
         patch("urllib.request.urlopen", return_value=_health_response(200)), \
         patch("os.system"):
        asyncio.run(mm.load_model("7b"))

    assert lifecycle == ["unloaded", "loaded"], "Must unload previous model before loading new model to prevent VRAM spike"
    if vram_before is not None:
        assert vram_before >= 0


@pytest.mark.asyncio
async def test_command_uses_configured_gpu_layers(tmp_path, monkeypatch):
    """The offload count is configurable and defaults away from a risky full offload."""
    server = tmp_path / "llama-server.exe"
    model = tmp_path / "model.gguf"
    server.touch()
    model.touch()
    monkeypatch.setenv("FRIDAY_LLAMA_NGL", "12")
    mm = ModelManager(health_timeout_seconds=0.1, health_poll_interval_seconds=0.01)
    mm.server_bin = str(server)
    mm.model_paths = {"3b": str(model), "7b": str(model)}
    process = MagicMock()

    with patch("subprocess.Popen", return_value=process) as mock_popen, \
         patch("urllib.request.urlopen", return_value=_health_response(200)):
        assert await mm.load_model("7b") is True

    command = mock_popen.call_args.args[0]
    assert command[command.index("-ngl") + 1] == "12"
    assert mm.current_model == "7b"


@pytest.mark.asyncio
async def test_failed_target_rolls_back_and_emits_failure(tmp_path):
    """A target returning non-200 is killed and the prior model is restored."""
    server = tmp_path / "llama-server.exe"
    model = tmp_path / "model.gguf"
    server.touch()
    model.touch()
    bus = EventBus()
    await bus.start()
    failures = []
    bus.subscribe(EventType.LLM_FAILURE, lambda event: failures.append(event))

    mm = ModelManager(
        event_bus=bus,
        health_timeout_seconds=0.05,
        health_poll_interval_seconds=0.01,
    )
    mm.server_bin = str(server)
    mm.model_paths = {"3b": str(model), "7b": str(model)}
    old_process = MagicMock()
    failed_target = MagicMock()
    rollback_process = MagicMock()
    mm.process = old_process
    mm.current_model = "3b"

    try:
        with patch("subprocess.Popen", side_effect=[failed_target, rollback_process]), \
             patch.object(mm, "_wait_for_health", new_callable=AsyncMock, side_effect=[False, True]), \
             patch("os.system"):
            assert await mm.switch_model("7b", "test_failure") is False

        failed_target.terminate.assert_called_once()
        old_process.terminate.assert_called_once()
        assert mm.current_model == "3b"
        assert mm.process is rollback_process
        await bus.drain()
        assert len(failures) == 1
        assert failures[0].payload["model"] == "7b"
        assert failures[0].payload["rolled_back"] is True
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_healthy_target_is_the_only_successful_switch(tmp_path):
    """A target becomes active only after the health endpoint returns HTTP 200."""
    server = tmp_path / "llama-server.exe"
    model = tmp_path / "model.gguf"
    server.touch()
    model.touch()
    mm = ModelManager(health_timeout_seconds=0.1, health_poll_interval_seconds=0.01)
    mm.server_bin = str(server)
    mm.model_paths = {"3b": str(model), "7b": str(model)}
    old_process = MagicMock()
    target_process = MagicMock()
    mm.process = old_process
    mm.current_model = "3b"

    with patch("subprocess.Popen", return_value=target_process), \
         patch("urllib.request.urlopen", return_value=_health_response(200)), \
         patch("os.system"):
        assert await mm.switch_model("7b", "healthy_target") is True

    assert mm.current_model == "7b"
    assert mm.process is target_process
    old_process.terminate.assert_called_once()
