import asyncio
import errno
import json
from datetime import UTC, datetime

import websockets
from websockets.asyncio.server import serve, ServerConnection
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.workers.base_worker import BaseWorker

PUBLIC_EVENTS = {
    EventType.SYSTEM_READY,
    EventType.USER_SPEECH,
    EventType.STATE_UPDATED,
    EventType.ASSISTANT_RESPONSE,
    EventType.TTS_PLAY,
    EventType.ACTION_REQUEST,
    EventType.ACTION_RESULT,
    EventType.ERROR,
    EventType.HEARTBEAT,
}

import base64

class EventEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return base64.b64encode(obj).decode('utf-8')
        return super().default(obj)

class WebsocketServerWorker(BaseWorker):
    """
    WebSocket Server Worker to expose the FRIDAY Runtime to remote clients.
    This enables mobile apps, dashboards, or remote nodes to connect to the EventBus.
    """
    def __init__(self, event_bus: EventBus, host: str = "0.0.0.0", port: int = 8765, metrics=None):
        super().__init__("websocket_server", event_bus)
        self.host = host
        self.port = port
        self.metrics = metrics
        self.clients: set[ServerConnection] = set()
        self._server = None

    async def run(self) -> None:
        # Subscribing to public events to broadcast
        for event_type in PUBLIC_EVENTS:
            self.event_bus.subscribe(event_type, self._broadcast_event)
        
        await super().run()

    async def _broadcast_event(self, event: Event) -> None:
        if not self.clients:
            return
            
        message = json.dumps({
            "event_type": event.event_type.value,
            "payload": event.payload,
            "correlation_id": event.correlation_id,
            "timestamp": event.created_at.isoformat()
        }, cls=EventEncoder)
        
        # Send to all connected clients
        websockets.broadcast(self.clients, message)

    async def handler(self, websocket: ServerConnection) -> None:
        self.clients.add(websocket)
        self.logger.info("websocket_client_connected", extra={"client": str(websocket.remote_address)})
        
        try:
            # Welcome message
            await websocket.send(json.dumps({
                "event_type": "SYSTEM_WELCOME",
                "payload": {"message": "Connected to FRIDAY Runtime"}
            }))
            
            async for message in websocket:
                try:
                    data = json.loads(message)
                    event_type_str = data.get("event_type")
                    payload = data.get("payload", {})
                    correlation_id = data.get("correlation_id")
                    
                    if not event_type_str:
                        continue
                        
                    try:
                        event_type = EventType(event_type_str)
                    except ValueError:
                        self.logger.warning("invalid_event_type_received", extra={"type": event_type_str})
                        continue
                        
                    event = Event.create(
                        event_type,
                        payload,
                        source="websocket_client",
                        correlation_id=correlation_id
                    )
                    await self.event_bus.publish(event)
                    
                except json.JSONDecodeError:
                    self.logger.warning("invalid_json_received")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.remove(websocket)
            self.logger.info("websocket_client_disconnected", extra={"client": str(websocket.remote_address)})

    @staticmethod
    def _is_port_in_use(exc: BaseException) -> bool:
        if isinstance(exc, OSError):
            err_str = str(exc)
            return (
                exc.errno in {errno.EADDRINUSE, 10048}
                or getattr(exc, "winerror", None) == 10048
                or "10048" in err_str
                or "address already in use" in err_str.lower()
            )
        return False

    @staticmethod
    def _kill_process_on_port(port: int) -> bool:
        import subprocess
        import os
        import signal
        try:
            result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if f":{port}" in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        pid_str = parts[-1]
                        try:
                            pid = int(pid_str)
                            if pid == os.getpid():
                                continue
                            if os.name == "nt":
                                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
                            else:
                                os.kill(pid, signal.SIGKILL)
                            return True
                        except (ValueError, OSError):
                            pass
        except Exception:
            pass
        return False

    async def work(self) -> None:
        self._server = None
        max_attempts = 10
        port_attempt = self.port
        for attempt in range(max_attempts):
            if attempt == 0:
                self._kill_process_on_port(port_attempt)
            try:
                self._server = await serve(self.handler, self.host, port_attempt)
                self.port = port_attempt
                self.logger.info("websocket_server_started", extra={"host": self.host, "port": self.port})
                break
            except OSError as exc:
                if self._is_port_in_use(exc) and attempt < max_attempts - 1:
                    self.logger.warning("websocket_port_collision", extra={"port": port_attempt, "next": port_attempt + 1})
                    port_attempt += 1
                else:
                    if self._is_port_in_use(exc):
                        if self.metrics is not None:
                            self.metrics.websocket_bind_failures += 1
                        self.logger.error(
                            "websocket_port_in_use",
                            extra={
                                "host": self.host,
                                "port": port_attempt,
                                "hint": "netstat -ano | findstr :8765 then taskkill /PID <pid> /F",
                            },
                        )
                        self.health.mark_disabled()
                        while not self.should_stop:
                            self.health.last_heartbeat = datetime.now(UTC)
                            self.health.current_task = "websocket_disabled_port_in_use"
                            await asyncio.sleep(5.0)
                        return
                    raise

        try:
            while not self.should_stop:
                self.heartbeat(f"clients: {len(self.clients)}")
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise
        finally:
            server = self._server
            if server is not None:
                server.close()
                await server.wait_closed()
                self._server = None
            self.logger.info("websocket_server_stopped")
