import asyncio
from typing import Any
from .tool_models import ToolRisk
from ..events.event_types import EventType
from ..events.models import Event


class ConfirmationSystem:
    def __init__(self, event_bus: Any):
        self.event_bus = event_bus
        self._pending_confirmations = {}  # correlation_id -> asyncio.Future

    async def wait_for_confirmation(self, correlation_id: str, tool_name: str, risk: ToolRisk) -> bool:
        """
        Wait for human operator approval for RESTRICTED or DANGEROUS actions.
        Returns True if approved, False if denied.
        """
        if risk == ToolRisk.SAFE:
            return True

        if risk == ToolRisk.FORBIDDEN:
            return False

        # Register future for async resolution
        future = asyncio.get_running_loop().create_future()
        self._pending_confirmations[correlation_id] = future

        # Publish request for UI/Operator interaction
        await self.event_bus.publish(Event.create(
            EventType.ACTION_CONFIRMATION_REQUIRED,
            {
                "correlation_id": correlation_id,
                "tool_name": tool_name,
                "risk_level": risk.value
            },
            "confirmation_system",
            correlation_id
        ))

        try:
            # Wait for operator response (Caller handles timeout)
            result = await future
            return result
        except asyncio.CancelledError:
            return False
        finally:
            self._pending_confirmations.pop(correlation_id, None)

    def resolve_confirmation(self, correlation_id: str, approved: bool):
        """Called when user provides input via UI/CLI."""
        future = self._pending_confirmations.get(correlation_id)
        if future and not future.done():
            future.set_result(approved)
