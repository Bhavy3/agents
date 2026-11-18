import asyncio
import inspect
import time
import logging
from typing import Any, Dict
from ..asyncio_utils import spawn_background
from ..workers.base_worker import BaseWorker
from ..events.bus import EventBus
from ..events.event_types import EventType
from ..events.models import Event
from .capability_loader import CapabilityLoader
from .tool_models import ToolResult, ToolRisk, ToolAuditEntry
from .tool_registry import ToolRegistry
from .tool_validator import ToolValidator
from .confirmations import ConfirmationSystem
from .verification import EffectVerifier
from .browser_tools import WEB_TOOL_TIMEOUT_SECONDS

WEB_TOOLS = {"search_web", "research_web", "open_section"}


class ToolWorker(BaseWorker):
    def __init__(self, event_bus: EventBus, metrics: Any = None, query_client: Any = None):
        super().__init__("tool_worker", event_bus)
        self.metrics = metrics
        self.registry = ToolRegistry(event_bus=event_bus, query_client=query_client)
        self.validator = ToolValidator()
        self.confirmations = ConfirmationSystem(event_bus)
        # Capability contracts drive effect verification. A manifest problem is
        # logged by the loader and degrades to "no contract", never to a crash.
        self.capabilities = CapabilityLoader().load_all()
        self.verifier = EffectVerifier()
        self._active_tasks: Dict[str, asyncio.Task] = {}
        
        # Action history/Audit (kept in memory for Phase 9.0 metrics, persisted in later phases)
        self.audit_log: list[ToolAuditEntry] = []

    async def run(self) -> None:
        self.event_bus.subscribe(EventType.ACTION_REQUESTED, self.handle_action_request)
        # Operator (CLI/voice) resolves RESTRICTED/DANGEROUS confirmation requests.
        self.event_bus.subscribe(EventType.OPERATOR_CONFIRMATION_RESPONSE, self._on_confirmation_response)
        await super().run()

    async def _on_confirmation_response(self, event: Event) -> None:
        correlation_id = str(event.payload.get("correlation_id", ""))
        if not correlation_id:
            return
        approved = bool(event.payload.get("approved", False))
        self.confirmations.resolve_confirmation(correlation_id, approved)

    async def _publish_safe(self, event: Event) -> None:
        """Drop lifecycle publishes when the bus is already stopped instead of raising."""
        if not getattr(self.event_bus, "_running", False):
            return
        await self.event_bus.publish(event)

    async def work(self) -> None:
        while not self.should_stop:
            self.heartbeat(f"tools [active={len(self._active_tasks)} audits={len(self.audit_log)}]")
            await asyncio.sleep(1.0)

    async def handle_action_request(self, event: Event) -> None:
        # Offload to a background task to avoid deadlocking the EventBus dispatcher
        spawn_background(self._supervised_execution(event))

    async def _supervised_execution(self, event: Event) -> None:
        try:
            payload = event.payload
            correlation_id = event.correlation_id
            tool_name = payload.get("intent")
            parameters = payload.get("parameters", {})

            # 1. Validation
            validation = self.validator.validate_request(tool_name, parameters)
            if not validation.allowed:
                await self._publish_safe(Event.create(
                    EventType.ACTION_DENIED,
                    {"reason": validation.reason, "tool_name": tool_name},
                    self.name,
                    correlation_id
                ))
                await self._publish_safe(Event.create(
                    EventType.RESPONSE_READY,
                    {"text": f"Permission Denied: {validation.reason}"},
                    self.name,
                    correlation_id
                ))
                return

            # 2. Confirmation (if restricted/dangerous)
            approved = await self.confirmations.wait_for_confirmation(correlation_id, tool_name, validation.risk)
            if not approved:
                await self._publish_safe(Event.create(
                    EventType.ACTION_DENIED,
                    {"reason": "user_refused_permission", "tool_name": tool_name},
                    self.name,
                    correlation_id
                ))
                await self._publish_safe(Event.create(
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
                await self._publish_safe(Event.create(
                    EventType.ACTION_CANCELLED,
                    {"tool_name": tool_name},
                    self.name,
                    correlation_id
                ))
                await self._publish_safe(Event.create(
                    EventType.RESPONSE_READY,
                    {"text": f"Action {tool_name} was cancelled."},
                    self.name,
                    correlation_id
                ))
                # Only our own cancellation propagates; a cancelled tool task
                # is reported and the worker keeps running.
                if not task.cancelled():
                    raise
            finally:
                self._active_tasks.pop(correlation_id, None)
        except Exception as e:
            self.logger.exception("supervised_execution_failed")

    @staticmethod
    def _filter_tool_parameters(name: str, tool_func: Any, params: dict) -> dict:
        """Drop parameters the tool cannot accept, and say so in the log.

        A planner that invents `num_results` used to crash the tool with
        TypeError instead of running with the parameters it does support.
        """
        try:
            signature = inspect.signature(tool_func)
        except (TypeError, ValueError):
            return params
        parameters = signature.parameters
        if any(p.kind is p.VAR_KEYWORD for p in parameters.values()):
            return params
        allowed = {
            param_name
            for param_name, parameter in parameters.items()
            if parameter.kind in (parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY)
        }
        dropped = sorted(set(params) - allowed)
        if not dropped:
            return params
        logger.warning("tool_parameter_dropped", extra={"tool": name, "dropped": dropped})
        return {key: value for key, value in params.items() if key in allowed}

    async def execute_tool(self, name: str, params: dict, correlation_id: str, risk: ToolRisk) -> ToolResult:
        tool_func = self.registry.get_tool(name)
        if not tool_func:
            err_msg = f"Tool '{name}' not found in registry"
            await self.event_bus.publish(Event.create(EventType.ACTION_FAILED, {"error": err_msg}, self.name, correlation_id))
            await self.event_bus.publish(Event.create(EventType.RESPONSE_READY, {"text": err_msg}, self.name, correlation_id))
            return ToolResult(False, "", err_msg)

        if name in {"search_web", "research_web"} and not (isinstance(params.get("query"), str) and params.get("query").strip()):
            await self.event_bus.publish(Event.create(
                EventType.ACTION_FAILED,
                {"tool_name": name, "error": "missing_query"},
                self.name,
                correlation_id,
            ))
            return ToolResult(False, "", "missing_query")

        start_time = time.time()
        await self.event_bus.publish(Event.create(
            EventType.ACTION_STARTED,
            {"tool_name": name},
            self.name,
            correlation_id
        ))

        timeout = WEB_TOOL_TIMEOUT_SECONDS if name in WEB_TOOLS else 15.0
        params = self._filter_tool_parameters(name, tool_func, params)
        try:
            # Web retrieval includes fallback searches and concurrent page
            # reads, each with smaller deadlines inside this overall budget.
            result = await asyncio.wait_for(tool_func(**params), timeout=timeout)
            duration = (time.time() - start_time) * 1000

            # Check the effect, not the tool's claim about it. Only enforced when
            # evidence exists; otherwise the outcome stays explicitly unchecked.
            verdict = self.verifier.verify(self.capabilities.get(name), params, result)
            if verdict.checked and not verdict.passed:
                message = (
                    verdict.detail
                    if verdict.detail.startswith("verification failed")
                    else f"verification failed: {verdict.detail}"
                )
                self.audit_log.append(ToolAuditEntry(
                    timestamp=time.time(),
                    tool_name=name,
                    parameters=params,
                    risk_level=risk,
                    success=False,
                    duration_ms=duration,
                    correlation_id=correlation_id,
                    error=message,
                    verified=False,
                ))
                if self.metrics:
                    self.metrics.tools_executed += 1
                    self.metrics.average_tool_latency_ms = (
                        self.metrics.average_tool_latency_ms * 0.9
                    ) + (duration * 0.1)
                await self.event_bus.publish(Event.create(
                    EventType.ACTION_FAILED,
                    {
                        "tool_name": name,
                        "error": message,
                        "output": result.output,
                        "verification_failed": True,
                    },
                    self.name,
                    correlation_id,
                ))
                if name not in WEB_TOOLS:
                    await self.event_bus.publish(Event.create(
                        EventType.RESPONSE_READY,
                        {"text": f"Action {name} could not be confirmed: {verdict.detail}"},
                        self.name,
                        correlation_id,
                    ))
                return ToolResult(False, result.output, message, metadata=dict(result.metadata or {}))
            
            # Audit recording
            entry = ToolAuditEntry(
                timestamp=time.time(),
                tool_name=name,
                parameters=params,
                risk_level=risk,
                success=result.success,
                duration_ms=duration,
                correlation_id=correlation_id,
                error=result.error,
                verified=verdict.passed if verdict.checked else None,
            )
            self.audit_log.append(entry)
            
            if self.metrics:
                self.metrics.tools_executed += 1
                self.metrics.average_tool_latency_ms = (self.metrics.average_tool_latency_ms * 0.9) + (duration * 0.1)

            await self.event_bus.publish(Event.create(
                EventType.ACTION_COMPLETED,
                {
                    "tool_name": name,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                    "verified": verdict.passed if verdict.checked else None,
                    "verification": verdict.detail,
                },
                self.name,
                correlation_id
            ))
            
            response_text = result.output if result.success else f"Action failed: {result.error}"
            if not response_text:
                response_text = f"Action {name} completed successfully."
            if name not in WEB_TOOLS:
                await self.event_bus.publish(Event.create(
                    EventType.RESPONSE_READY,
                    {"text": response_text},
                    self.name,
                    correlation_id
                ))
            
            return result

        except asyncio.TimeoutError:
            err_msg = f"Execution timed out ({timeout:g}s limit)"
            await self.event_bus.publish(Event.create(EventType.ACTION_TIMEOUT, {"tool_name": name}, self.name, correlation_id))
            if name not in WEB_TOOLS:
                await self.event_bus.publish(Event.create(EventType.RESPONSE_READY, {"text": f"Action {name} timed out."}, self.name, correlation_id))
            return ToolResult(False, "", err_msg)
        except Exception as e:
            self.logger.exception("tool_execution_failed")
            await self.event_bus.publish(Event.create(EventType.ACTION_FAILED, {"tool_name": name, "error": str(e)}, self.name, correlation_id))
            if name not in WEB_TOOLS:
                await self.event_bus.publish(Event.create(EventType.RESPONSE_READY, {"text": f"Action failed with error: {str(e)}"}, self.name, correlation_id))
            return ToolResult(False, "", str(e))

    async def stop(self) -> None:
        # Interruption safety: cancel all pending tasks
        for task in self._active_tasks.values():
            task.cancel()
        await super().stop()
