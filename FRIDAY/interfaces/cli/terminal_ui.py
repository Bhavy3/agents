from __future__ import annotations

import asyncio

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.logging.logger import get_logger
from interfaces.cli.health_dashboard import TerminalHealthDashboard


class TerminalUI:
    def __init__(self, event_bus: EventBus, dashboard: TerminalHealthDashboard | None = None) -> None:
        self.event_bus = event_bus
        self.dashboard = dashboard
        self.logger = get_logger("interfaces.cli")
        self._running = False

    async def start(self) -> None:
        self._running = True
        self.event_bus.subscribe(EventType.RESPONSE_READY, self.handle_response)
        print("FRIDAY online. Type 'help' or 'exit'.")
        while self._running:
            try:
                text = await asyncio.to_thread(input, "You > ")
            except (EOFError, KeyboardInterrupt):
                text = "exit"
            cmd = text.strip().lower()
            if cmd in {"status", "health", "dashboard"} and self.dashboard is not None:
                print(self.dashboard.render())
                continue
            if cmd == "workers" and self.dashboard is not None:
                print(self.dashboard.render_workers())
                continue
            if cmd == "metrics" and self.dashboard is not None:
                print(self.dashboard.render_metrics())
                continue
            if cmd == "queue":
                print(f"queue_depth={self.event_bus.queue_depth}")
                continue
            if cmd.startswith("restart ") and self.dashboard is not None:
                worker_name = cmd.split(" ", 1)[1]
                if self.dashboard.supervisor.restart_worker(worker_name):
                    print(f"Restarting worker {worker_name}")
                else:
                    print(f"Worker {worker_name} not found")
                continue
            if cmd.startswith("quarantine ") and self.dashboard is not None:
                worker_name = cmd.split(" ", 1)[1]
                if self.dashboard.supervisor.quarantine_worker(worker_name):
                    print(f"Quarantining worker {worker_name}")
                else:
                    print(f"Worker {worker_name} not found")
                continue
            if cmd == "help":
                print("Commands: status, workers, metrics, queue, restart <worker>, quarantine <worker>, help, exit")
                continue
            
            await self.event_bus.publish(
                Event.create(EventType.USER_TEXT_RECEIVED, {"text": text}, "terminal_ui")
            )
            if cmd in {"exit", "quit", "shutdown friday", "stop friday"}:
                await self.event_bus.publish(
                    Event.create(EventType.SYSTEM_SHUTDOWN_REQUESTED, {}, "terminal_ui")
                )
                self._running = False

    async def stop(self) -> None:
        self._running = False

    async def handle_response(self, event: Event) -> None:
        print(f"FRIDAY > {event.payload.get('text', '')}")
