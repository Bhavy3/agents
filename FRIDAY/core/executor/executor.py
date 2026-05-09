from __future__ import annotations

import asyncio
import uuid
from typing import Any

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.executor.command_registry import CommandRegistry
from core.executor.dry_run_actions import ExecutorResult
from core.executor.validation import CommandValidationPipeline, ActionRisk
from core.logging.logger import get_logger
from core.memory.command_history import CommandHistory, CommandHistoryEntry
from core.workers.base_worker import BaseWorker


class CommandExecutor(BaseWorker):
    """Safe action runtime with permission enforcement and execution isolation."""

    def __init__(
        self,
        event_bus: EventBus,
        command_registry: CommandRegistry,
        command_history: CommandHistory | None = None,
        validation_pipeline: CommandValidationPipeline | None = None,
        command_timeout_seconds: float = 15.0,
    ) -> None:
        super().__init__("action_executor", event_bus)
        self.command_registry = command_registry
        self.command_history = command_history or CommandHistory()
        self.validation_pipeline = validation_pipeline or CommandValidationPipeline()
        self.command_timeout_seconds = command_timeout_seconds
        self.logger = get_logger("executor")
        
        self._active_actions: dict[str, asyncio.Task] = {}

    async def run(self) -> None:
        self.event_bus.subscribe(EventType.ACTION_REQUESTED, self.handle_action_request)
        # Interruption safety: cancel actions if user speaks
        self.event_bus.subscribe(EventType.CONVERSATION_INTERRUPTED, self.handle_interruption)
        self.event_bus.subscribe(EventType.SPEECH_STARTED, self.handle_interruption)
        
        self.logger.info("action_executor_started")
        await super().run()

    async def handle_action_request(self, event: Event) -> None:
        payload = event.payload
        action_id = payload.get("action_id", str(uuid.uuid4()))
        intent = str(payload.get("intent", "unknown"))
        parameters = payload.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        
        # 1. Deterministic Validation
        validation = self.validation_pipeline.validate(intent, parameters)
        
        await self.event_bus.publish(
            Event.create(
                EventType.ACTION_VALIDATED,
                {
                    "action_id": action_id,
                    "allowed": validation.allowed,
                    "requires_confirmation": validation.requires_confirmation,
                    "risk_level": str(validation.risk_level),
                },
                self.name,
                event.correlation_id,
            )
        )
        
        if not validation.allowed:
            self.logger.warning("action_denied", extra={"intent": intent, "reason": validation.reason})
            
            # Record in history even if denied
            self.command_history.add(
                CommandHistoryEntry(
                    command=intent,
                    result=f"Denied: {validation.reason}",
                    success=False,
                    intended_action=intent,
                    metadata={
                        "action_id": action_id,
                        "risk_level": str(validation.risk_level),
                        "requires_confirmation": validation.requires_confirmation,
                        "reason": validation.reason,
                    },
                )
            )
            
            await self.event_bus.publish(
                Event.create(
                    EventType.ACTION_DENIED,
                    {"action_id": action_id, "reason": validation.reason},
                    self.name,
                    event.correlation_id,
                )
            )
            # Feedback to user
            await self.event_bus.publish(
                Event.create(
                    EventType.RESPONSE_READY,
                    {"text": f"Permission Denied: {validation.reason}"},
                    self.name,
                    event.correlation_id,
                )
            )
            return

        # 2. Execution Routing
        handler = self.command_registry.get(intent)
        if not handler:
            self.logger.error("action_handler_missing", extra={"intent": intent})
            await self.event_bus.publish(
                Event.create(
                    EventType.ACTION_FAILED,
                    {"action_id": action_id, "error": f"Unknown command: {intent}"},
                    self.name,
                    event.correlation_id,
                )
            )
            return

        # Start isolated execution task
        task = asyncio.create_task(
            self._execute_action(action_id, intent, parameters, handler, event.correlation_id)
        )
        self._active_actions[action_id] = task
        task.add_done_callback(lambda _: self._active_actions.pop(action_id, None))

    async def _execute_action(
        self, action_id: str, intent: str, parameters: dict[str, Any], handler: Any, correlation_id: str | None
    ) -> None:
        await self.event_bus.publish(
            Event.create(EventType.ACTION_STARTED, {"action_id": action_id}, self.name, correlation_id)
        )
        
        import time
        start_time = time.perf_counter()
        
        try:
            # Execution with timeout
            result: ExecutorResult = await asyncio.wait_for(
                handler(parameters), 
                timeout=self.command_timeout_seconds
            )
            execution_time = time.perf_counter() - start_time
            
            await self.event_bus.publish(
                Event.create(
                    EventType.ACTION_COMPLETED,
                    {"action_id": action_id, "result": result.message},
                    self.name,
                    correlation_id,
                )
            )
            
            # Record in history
            self.command_history.add(
                CommandHistoryEntry(
                    command=intent,
                    result=result.message,
                    success=result.success,
                    intended_action=result.metadata.get("intended_action", intent),
                    metadata={
                        "action_id": action_id,
                        "execution_time": execution_time,
                        "details": result.metadata,
                    },
                )
            )
            
            # Emit response for user
            await self.event_bus.publish(
                Event.create(
                    EventType.RESPONSE_READY,
                    {"text": result.message},
                    self.name,
                    correlation_id,
                )
            )
            
        except asyncio.CancelledError:
            self.logger.info("action_cancelled", extra={"action_id": action_id})
            # No need to publish here, handle_interruption does it
            raise
        except (asyncio.TimeoutError, TimeoutError):
            self.logger.warning("action_timeout", extra={"action_id": action_id, "intent": intent})
            await self.event_bus.publish(
                Event.create(EventType.ACTION_TIMEOUT, {"action_id": action_id}, self.name, correlation_id)
            )
            error_msg = f"The action '{intent}' timed out after {self.command_timeout_seconds}s."
            
            self.command_history.add(
                CommandHistoryEntry(
                    command=intent,
                    result=error_msg,
                    success=False,
                    intended_action=intent,
                    metadata={"action_id": action_id, "error": "TimeoutError"},
                )
            )
            
            await self.event_bus.publish(
                Event.create(
                    EventType.RESPONSE_READY,
                    {"text": error_msg},
                    self.name,
                    correlation_id,
                )
            )
        except Exception as e:
            self.logger.exception("action_execution_failed", extra={"action_id": action_id, "intent": intent})
            await self.event_bus.publish(
                Event.create(
                    EventType.ACTION_FAILED,
                    {"action_id": action_id, "error": str(e)},
                    self.name,
                    correlation_id,
                )
            )
            
            await self.event_bus.publish(
                Event.create(
                    EventType.ERROR_OCCURRED,
                    {"component": "action_executor", "intent": intent, "error": str(e)},
                    self.name,
                    correlation_id,
                )
            )
            
            error_msg = f"I encountered an error executing '{intent}': {str(e)}"
            
            self.command_history.add(
                CommandHistoryEntry(
                    command=intent,
                    result=error_msg,
                    success=False,
                    intended_action=intent,
                    metadata={"action_id": action_id, "error": str(e)},
                )
            )
            
            await self.event_bus.publish(
                Event.create(
                    EventType.RESPONSE_READY,
                    {"text": error_msg},
                    self.name,
                    correlation_id,
                )
            )

    async def handle_interruption(self, event: Event) -> None:
        """Cancel all active actions immediately on interruption."""
        if not self._active_actions:
            return
            
        self.logger.info("interrupting_active_actions", extra={"count": len(self._active_actions)})
        
        for action_id, task in list(self._active_actions.items()):
            if not task.done():
                task.cancel()
                await self.event_bus.publish(
                    Event.create(
                        EventType.ACTION_CANCELLED,
                        {"action_id": action_id, "reason": "interruption"},
                        self.name,
                        event.correlation_id,
                    )
                )
        self._active_actions.clear()

    async def work(self) -> None:
        while not self.should_stop:
            self.heartbeat(f"actions [active={len(self._active_actions)} history={len(self.command_history.recent())}]")
            await asyncio.sleep(1.0)
