import pytest
from unittest.mock import MagicMock

from core.events.bus import EventBus
from interfaces.cli.terminal_ui import TerminalUI


@pytest.mark.asyncio
async def test_terminal_ui_handle_command_filters_operator_commands():
    bus = EventBus()
    ui = TerminalUI(bus, dashboard=None, cli_input_enabled=True)

    handled = await ui.handle_command("exit")
    assert handled is True
    assert ui._running is False

    handled = await ui.handle_command("help")
    assert handled is True

    handled = await ui.handle_command("queue")
    assert handled is True

    handled = await ui.handle_command("not a command")
    assert handled is False


@pytest.mark.asyncio
async def test_terminal_ui_handle_command_renders_dashboard_commands():
    bus = EventBus()
    fake_dashboard = MagicMock()
    fake_dashboard.render.return_value = "STATUS"
    fake_dashboard.render_workers.return_value = "WORKERS"
    fake_dashboard.render_metrics.return_value = "METRICS"

    ui = TerminalUI(bus, dashboard=fake_dashboard, cli_input_enabled=True)

    handled = await ui.handle_command("status")
    assert handled is True
    fake_dashboard.render.assert_called_once()

    handled = await ui.handle_command("workers")
    assert handled is True
    fake_dashboard.render_workers.assert_called_once()

    handled = await ui.handle_command("metrics")
    assert handled is True
    fake_dashboard.render_metrics.assert_called_once()
