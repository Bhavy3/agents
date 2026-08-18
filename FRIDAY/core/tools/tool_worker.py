import asyncio
import time
import logging
from typing import Any, Dict
from ..workers.base_worker import BaseWorker
from ..events.bus import EventBus
from ..events.event_types import EventType
from ..events.models import Event
from .tool_models import ToolResult, ToolRisk, ToolAuditEntry
from .tool_registry import ToolRegistry
from .tool_validator import ToolValidator
from .confirmations import ConfirmationSystem


class ToolWorker(BaseWorker):
    def __init__(self, event_bus: EventBus, metrics: Any = None):
        super().__init__("tool_worker", event_bus)
        self.metrics = metrics
        self.registry = ToolRegistry()
        self.validator = ToolValidator()
        self.confirmations = ConfirmationSystem(event_bus)
        self._active_tasks: Dict[str, asyncio.Task] = {}
        
        # Action history/Audit (kept in memory for Phase 9.0 metrics, persisted in later phases)
        self.audit_log: list[ToolAuditEntry] = []

    async def run(self) -> None:
        self.event_bus.subscribe(EventType.ACTION_REQUESTED, self.handle_action_request)
        # Integration with UI for confirmations
        # self.event_bus.subscribe(EventType.OPERATOR_CONFIRMATION_RESPONSE, self._on_confirmation_response)
        await super().run()

    async def work(self) -> None:
        while not self.should_stop:
            self.heartbeat(f"tools [active={len(self._active_tasks)} audits={len(self.audit_log)}]")
            await asyncio.sleep(1.0)

    async def handle_action_request(self, event: Event) -> None:
        # Offload to a background task to avoid deadlocking the EventBus dispatcher
        asyncio.create_task(self._supervised_execution(event))

    async def _supervised_execution(self, event: Event) -> None:
        try:
            payload = event.payload
            correlation_id = event.correlation_id
            tool_name = payload.get("intent")
            parameters = payload.get("parameters", {})

            # 1. Validation
            validation = self.validator.validate_request(tool_name, parameters)
            if not validation.allowed:
                await self.event_bus.publish(Event.create(
                    EventType.ACTION_DENIED,
                    {"reason": validation.reason, "tool_name": tool_name},
                    self.name,
                    correlation_id
                ))
                await self.event_bus.publish(Event.create(
                    EventType.RESPONSE_READY,
                    {"text": f"Permission Denied: {validation.reason}"},
                    self.name,
                    correlation_id
                ))
                return

            # 2. Confirmation (if restricted/dangerous)
            approved = await self.confirmations.wait_for_confirmation(correlation_id, tool_name, validation.risk)
            if not approved:
                await self.event_bus.publish(Event.create(
                    EventType.ACTION_DENIED,
                    {"reason": "user_refused_permission", "tool_name": tool_name},
                    self.name,
                    correlation_id
                ))
                await self.event_bus.publish(Event.create(
                    EventType.RESPONSE_READY,
                    {"text": "Action denied: User refused permission."},
                    self.name,
                    correlation_id
                ))
                return

            # 3. Execution
            task = asyncio.create_task(
                self.execute_tool(tool_name, parameters, correlation_id, validation.risk),
                name=f"tool_exec_{correlation_id}"
            )
            self._active_tasks[correlation_id] = task
            try:
                await task
            except asyncio.CancelledError:
                await self.event_bus.publish(Event.create(
                    EventType.ACTION_CANCELLED,
                    {"tool_name": tool_name},
                    self.name,
                    correlation_id
                ))
                await self.event_bus.publish(Event.create(
                    EventType.RESPONSE_READY,
                    {"text": f"Action {tool_name} was cancelled."},
                    self.name,
                    correlation_id
                ))
            finally:
                self._active_tasks.pop(correlation_id, None)
        except Exception as e:
            self.logger.exception("supervised_execution_failed")

    async def execute_tool(self, name: str, params: dict, correlation_id: str, risk: ToolRisk) -> ToolResult:
        tool_func = self.registry.get_tool(name)
        if not tool_func:
            err_msg = f"Tool '{name}' not found in registry"
            await self.event_bus.publish(Event.create(EventType.ACTION_FAILED, {"error": err_msg}, self.name, correlation_id))
            await self.event_bus.publish(Event.create(EventType.RESPONSE_READY, {"text": err_msg}, self.name, correlation_id))
            return ToolResult(False, "", err_msg)

        start_time = time.time()
        await self.event_bus.publish(Event.create(
            EventType.ACTION_STARTED,
            {"tool_name": name},
            self.name,
            correlation_id
        ))

        try:
            # Enforce tool timeout (default 15s)
            result = await asyncio.wait_for(tool_func(**params), timeout=15.0)
            duration = (time.time() - start_time) * 1000
            
            # Audit recording
            entry = ToolAuditEntry(
                timestamp=time.time(),
                tool_name=name,
                parameters=params,
                risk_level=risk,
                success=result.success,
                duration_ms=duration,
                correlation_id=correlation_id,
                error=result.error
            )
            self.audit_log.append(entry)
            
            if self.metrics:
                self.metrics.tools_executed += 1
                self.metrics.average_tool_latency_ms = (self.metrics.average_tool_latency_ms * 0.9) + (duration * 0.1)

            await self.event_bus.publish(Event.create(
                EventType.ACTION_COMPLETED,
                {"success": result.success, "output": result.output, "error": result.error},
                self.name,
                correlation_id
            ))
            
            response_text = result.output if result.success else f"Action failed: {result.error}"
            if not response_text:
                response_text = f"Action {name} completed successfully."
                
            await self.event_bus.publish(Event.create(
                EventType.RESPONSE_READY,
                {"text": response_text},
                self.name,
                correlation_id
            ))
            
            return result

        except asyncio.TimeoutError:
            err_msg = "Execution timed out (15s limit)"
            await self.event_bus.publish(Event.create(EventType.ACTION_TIMEOUT, {"tool_name": name}, self.name, correlation_id))
            await self.event_bus.publish(Event.create(EventType.RESPONSE_READY, {"text": f"Action {name} timed out."}, self.name, correlation_id))
            return ToolResult(False, "", err_msg)
        except Exception as e:
            self.logger.exception("tool_execution_failed")
            await self.event_bus.publish(Event.create(EventType.ACTION_FAILED, {"error": str(e)}, self.name, correlation_id))
            await self.event_bus.publish(Event.create(EventType.RESPONSE_READY, {"text": f"Action failed with error: {str(e)}"}, self.name, correlation_id))
            return ToolResult(False, "", str(e))

    async def stop(self) -> None:
        # Interruption safety: cancel all pending tasks
        for task in self._active_tasks.values():
            task.cancel()
        await super().stop()
