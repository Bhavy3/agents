from __future__ import annotations

import asyncio

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.logging.logger import get_logger
from interfaces.cli.health_dashboard import TerminalHealthDashboard


class TerminalUI:
    def __init__(
        self,
        event_bus: EventBus,
        dashboard: TerminalHealthDashboard | None = None,
        cli_input_enabled: bool = True,
    ) -> None:
        self.event_bus = event_bus
        self.dashboard = dashboard
        self.cli_input_enabled = cli_input_enabled
        self.logger = get_logger("interfaces.cli")
        self._running = False
        self._pending_confirmation: str | None = None

    async def start(self) -> None:
        self._running = True
        self.event_bus.subscribe(EventType.RESPONSE_READY, self.handle_response)
        self.event_bus.subscribe(EventType.ACTION_CONFIRMATION_REQUIRED, self.handle_confirmation_request)
        self.event_bus.subscribe(EventType.NEW_EMAIL, self.handle_new_email)
        print("FRIDAY online. Type 'help' or 'exit'.")
        if not self.cli_input_enabled:
            while self._running:
                await asyncio.sleep(0.1)
            return

        while self._running:
            try:
                text = await asyncio.to_thread(input, "You > ")
            except KeyboardInterrupt:
                text = "exit"
            except EOFError:
                # Stdin closed or non-interactive; keep FRIDAY alive in voice-only mode
                self.cli_input_enabled = False
                while self._running:
                    await asyncio.sleep(0.5)
                return
            await self.handle_command(text)

    async def handle_command(self, text: str) -> bool:
        cmd = text.strip().lower()
        if cmd in {"yes", "y", "no", "n"} and self._pending_confirmation is not None:
            correlation_id = self._pending_confirmation
            self._pending_confirmation = None
            approved = cmd in {"yes", "y"}
            if getattr(self.event_bus, "_running", False):
                await self.event_bus.publish(
                    Event.create(
                        EventType.OPERATOR_CONFIRMATION_RESPONSE,
                        {"correlation_id": correlation_id, "approved": approved},
                        "terminal_ui",
                        correlation_id,
                    )
                )
            print(f"{'Approved' if approved else 'Denied'}: {correlation_id}")
            return True
        if cmd in {"yes", "y", "no", "n"}:
            print("No action is waiting for confirmation.")
            return True
        if cmd in {"status", "health", "dashboard"} and self.dashboard is not None:
            print(self.dashboard.render())
            return True
        if cmd == "workers" and self.dashboard is not None:
            print(self.dashboard.render_workers())
            return True
        if cmd == "metrics" and self.dashboard is not None:
            print(self.dashboard.render_metrics())
            return True
        if cmd == "queue":
            print(f"queue_depth={self.event_bus.queue_depth}")
            return True
        if cmd.startswith("restart ") and self.dashboard is not None:
            worker_name = cmd.split(" ", 1)[1]
            if self.dashboard.supervisor.restart_worker(worker_name):
                print(f"Restarting worker {worker_name}")
            else:
                print(f"Worker {worker_name} not found")
            return True
        if cmd.startswith("quarantine ") and self.dashboard is not None:
            worker_name = cmd.split(" ", 1)[1]
            if self.dashboard.supervisor.quarantine_worker(worker_name):
                print(f"Quarantining worker {worker_name}")
            else:
                print(f"Worker {worker_name} not found")
            return True
        if cmd == "help":
            print("Commands: status, workers, metrics, queue, restart <worker>, quarantine <worker>, yes|no (confirm action), help, exit")
            return True

        if cmd in {"exit", "quit", "shutdown friday", "stop friday"}:
            if getattr(self.event_bus, "_running", False):
                await self.event_bus.publish(
                    Event.create(EventType.SYSTEM_SHUTDOWN_REQUESTED, {}, "terminal_ui")
                )
            self._running = False
            return True

        if getattr(self.event_bus, "_running", False):
            await self.event_bus.publish(
                Event.create(EventType.USER_TEXT_RECEIVED, {"text": text}, "terminal_ui")
            )
        return False

    async def stop(self) -> None:
        self._running = False

    async def handle_response(self, event: Event) -> None:
        print(f"FRIDAY > {event.payload.get('text', '')}")

    async def handle_new_email(self, event: Event) -> None:
        sender = str(event.payload.get("sender", "unknown"))
        subject = str(event.payload.get("subject", "(no subject)"))
        print(f"📬 New mail from {sender}: {subject}")

    async def handle_confirmation_request(self, event: Event) -> None:
        correlation_id = str(event.payload.get("correlation_id", ""))
        tool_name = str(event.payload.get("tool_name", "unknown"))
        risk_level = str(event.payload.get("risk_level", "unknown"))
        self._pending_confirmation = correlation_id
        print(f"CONFIRMATION REQUIRED: {tool_name} (risk: {risk_level})")
        print("Type 'yes' to allow or 'no' to refuse.")
