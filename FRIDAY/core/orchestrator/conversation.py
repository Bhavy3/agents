import asyncio
import time
import uuid
from typing import Optional

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.workers.base_worker import BaseWorker
from core.router.intent_router import IntentRouter
from core.llm.streaming_worker import StreamingLlmWorker
from core.personality.prompt_personality import PersonalityPromptInjector
from core.personality.models import PersonaMode, StyleConfig
from core.personality.presence import PresenceManager
from core.workflows.prompt_planner import PromptPlanner


class OrchestratorWorker(BaseWorker):
    """Coordinates conversation turns, routing, and interruptions."""

    def __init__(
        self,
        event_bus: EventBus,
        intent_router: IntentRouter,
        streaming_worker: StreamingLlmWorker,
        prompt_planner: Optional[PromptPlanner] = None,
        max_context_turns: int = 10,
        response_timeout_seconds: float = 30.0,
        interrupt_cooldown_seconds: float = 1.5,
    ) -> None:
        super().__init__("orchestrator", event_bus)
        self.intent_router = intent_router
        self.streaming_worker = streaming_worker
        self.prompt_planner = prompt_planner
        self.max_context_turns = max_context_turns
        self.response_timeout_seconds = response_timeout_seconds
        self.interrupt_cooldown_seconds = interrupt_cooldown_seconds
        self.injector = PersonalityPromptInjector()
        self.presence = PresenceManager()
        
        self.active_turn_id: str | None = None
        self.current_mode = PersonaMode.ENGINEERING
        self.current_style = StyleConfig(tone="focused", verbosity="concise", pacing="normal")
        self.active_speaker: str | None = None
        self.context: list[dict[str, str]] = []
        self._routing_task: asyncio.Task | None = None
        self._last_activity_time = time.perf_counter()
        
        # Interrupt storm protection
        self._interrupt_cooldown_until = 0.0
        self.interrupt_cooldown_seconds = 1.5

        # Stats
        self.active_conversations = 0
        self.interruptions = 0
        self.stale_drops = 0
        self.total_latency = 0.0
        self.routed_messages = 0

    async def run(self) -> None:
        self.event_bus.subscribe(EventType.STT_FINAL_TRANSCRIPT, self._handle_final_transcript)
        self.event_bus.subscribe(EventType.SPEECH_STARTED, self._handle_speech_started)

        # Map LLM Stream events to Conversation events
        self.event_bus.subscribe(EventType.STREAM_STARTED, self._handle_stream_started)
        self.event_bus.subscribe(EventType.STREAM_CHUNK, self._handle_stream_chunk)
        self.event_bus.subscribe(EventType.STREAM_COMPLETED, self._handle_stream_completed)
        self.event_bus.subscribe(EventType.STREAM_CANCELLED, self._handle_stream_cancelled)
        self.event_bus.subscribe(EventType.STREAM_TIMEOUT, self._handle_stream_timeout)

        # Handle CLI fallback if needed (Command console input bypasses STT)
        self.event_bus.subscribe(EventType.USER_TEXT_RECEIVED, self._handle_cli_text)
        
        # Personality updates
        self.event_bus.subscribe(EventType.PERSONALITY_STYLE_UPDATED, self._handle_personality_update)
        await super().run()

    async def _handle_speech_started(self, event: Event) -> None:
        """User started speaking. Interrupt any active assistant response."""
        now = time.perf_counter()
        self._last_activity_time = now
        
        # Interrupt storm debounce
        if now < self._interrupt_cooldown_until:
            return
        
        if self.active_speaker == "assistant" or self._routing_task is not None:
            self._interrupt_cooldown_until = now + self.interrupt_cooldown_seconds
            self.interruptions += 1
            self.logger.info("conversation_interrupted", extra={"turn_id": self.active_turn_id})
            
            # Cancel active routing/inference
            if self._routing_task and not self._routing_task.done():
                self._routing_task.cancel()
            self.streaming_worker.cancel_all()
            
            if self.active_turn_id:
                await self.event_bus.publish(
                    Event.create(
                        EventType.CONVERSATION_INTERRUPTED,
                        {"turn_id": self.active_turn_id, "reason": "user_interruption"},
                        self.name
                    )
                )
                
            self.active_speaker = "user"
            self._routing_task = None

    async def _handle_final_transcript(self, event: Event) -> None:
        """Process finalized text from STT."""
        text = event.payload.get("text", "").strip()
        if not text:
            return
            
        await self._handle_speech_started(event)
        await self._initiate_turn(text, event.correlation_id)

    async def _handle_cli_text(self, event: Event) -> None:
        """Process text directly from CLI."""
        text = event.payload.get("text", "").strip()
        if not text:
            return
            
        # Cancel active turn if CLI is used
        await self._handle_speech_started(event)
        await self._initiate_turn(text, event.correlation_id)

    async def _initiate_turn(self, text: str, correlation_id: str | None) -> None:
        self._last_activity_time = time.perf_counter()
        self.active_turn_id = str(uuid.uuid4())[:8]
        self.active_speaker = "user"
        
        await self.event_bus.publish(
            Event.create(
                EventType.CONVERSATION_TURN_STARTED,
                {"turn_id": self.active_turn_id, "speaker": "user"},
                self.name,
                correlation_id
            )
        )
        
        await self.event_bus.publish(
            Event.create(
                EventType.USER_MESSAGE_RECEIVED,
                {"turn_id": self.active_turn_id, "text": text},
                self.name,
                correlation_id
            )
        )
        
        # Human presence: Simulated thinking delay
        await self.presence.simulate_thinking_delay(self.current_style)
        
        # Human presence: Acknowledgment
        ack = self.presence.get_acknowledgment(self.current_style)
        if ack:
            await self.event_bus.publish(
                Event.create(
                    EventType.ASSISTANT_RESPONSE_PARTIAL,
                    {"turn_id": self.active_turn_id, "text": ack + " "},
                    self.name,
                    correlation_id
                )
            )

        # Append to context
        self.context.append({"role": "user", "content": text})
        if len(self.context) > self.max_context_turns * 2:
            self.context = self.context[-(self.max_context_turns * 2):]
            
        # Yield to assistant
        self.active_speaker = "assistant"
        
        # Spawn routing task so Orchestrator remains unblocked
        self._routing_task = asyncio.create_task(
            self._route_and_execute(text, self.active_turn_id, correlation_id)
        )

    async def _handle_personality_update(self, event: Event) -> None:
        self.current_mode = PersonaMode(event.payload["persona_mode"])
        style_data = event.payload["style_config"]
        self.current_style = StyleConfig(
            tone=style_data["tone"],
            verbosity=style_data["verbosity"],
            pacing=style_data["pacing"],
            humor_level=style_data.get("humor_level", 0.0)
        )

    async def _route_and_execute(self, text: str, turn_id: str, correlation_id: str | None) -> None:
        start_time = time.perf_counter()
        try:
            # Generate personality instructions
            personality_instructions = self.injector.get_style_instructions(self.current_style, self.current_mode)
            
            # Check if this should be a multi-step workflow
            if self.prompt_planner and ("fix" in text.lower() or "debug" in text.lower() or "workflow" in text.lower()):
                self.logger.info("attempting_workflow_planning", extra={"goal": text})
                plan = await self.prompt_planner.create_plan_for_goal(text)
                if plan:
                    self.logger.info("workflow_plan_generated", extra={"steps": len(plan)})
                    # Convert dict plan to engine format and start
                    from core.app import FridayApp
                    # We need access to the workflow worker
                    # For simplicity in this session, we'll emit a WORKFLOW_STARTED event
                    # But the requirement is to use the engine.
                    # Since Orchestrator doesn't have direct ref to WorkflowWorker instance, 
                    # we'll assume it's part of the engine reachable via app context or we pass it in.
                    
                    # Better: publish WORKFLOW_REQUESTED
                    await self.event_bus.publish(Event.create(
                        EventType.ACTION_GRAPH_STARTED,
                        {"goal": text, "steps": plan},
                        self.name,
                        correlation_id
                    ))
                    return

            # Otherwise, proceed with simple routing
            mock_event = Event.create(EventType.USER_MESSAGE_RECEIVED, {"text": text}, self.name, correlation_id)
            await self.intent_router.handle_user_text(mock_event, personality_instructions=personality_instructions)
            self.routed_messages += 1
            
            # If the routing finishes successfully
            duration = time.perf_counter() - start_time
            await self.event_bus.publish(
                Event.create(
                    EventType.CONVERSATION_TURN_ENDED,
                    {"turn_id": turn_id, "duration": round(duration, 3)},
                    self.name,
                    correlation_id
                )
            )
        except asyncio.CancelledError:
            self.logger.info("routing_cancelled", extra={"turn_id": turn_id})
            # Cancellation is handled in _handle_speech_started
        except Exception as e:
            self.logger.error("routing_failed", extra={"error": str(e), "turn_id": turn_id})
        finally:
            if self.active_turn_id == turn_id:
                self._routing_task = None

    # Translating LLM Stream Events to Conversation Events
    async def _handle_stream_started(self, event: Event) -> None:
        if self.active_speaker != "assistant":
            return
        await self.event_bus.publish(
            Event.create(
                EventType.ASSISTANT_RESPONSE_STARTED,
                {"turn_id": self.active_turn_id},
                self.name,
                event.correlation_id
            )
        )

    async def _handle_stream_chunk(self, event: Event) -> None:
        if self.active_speaker != "assistant":
            return
        await self.event_bus.publish(
            Event.create(
                EventType.ASSISTANT_RESPONSE_PARTIAL,
                {"turn_id": self.active_turn_id, "text": event.payload.get("chunk", "")},
                self.name,
                event.correlation_id
            )
        )

    async def _handle_stream_completed(self, event: Event) -> None:
        if self.active_speaker != "assistant":
            return
            
        full_text = event.payload.get("full_text", "")
        self.context.append({"role": "assistant", "content": full_text})
            
        await self.event_bus.publish(
            Event.create(
                EventType.ASSISTANT_RESPONSE_COMPLETED,
                {"turn_id": self.active_turn_id, "text": full_text},
                self.name,
                event.correlation_id
            )
        )

    async def _handle_stream_cancelled(self, event: Event) -> None:
        if self.active_speaker != "assistant":
            return
        await self.event_bus.publish(
            Event.create(
                EventType.ASSISTANT_RESPONSE_CANCELLED,
                {"turn_id": self.active_turn_id, "reason": event.payload.get("reason", "unknown")},
                self.name,
                event.correlation_id
            )
        )

    async def _handle_stream_timeout(self, event: Event) -> None:
        if self.active_speaker != "assistant":
            return
        await self.event_bus.publish(
            Event.create(
                EventType.CONVERSATION_TIMEOUT,
                {"turn_id": self.active_turn_id, "timeout_type": event.payload.get("timeout_type", "unknown")},
                self.name,
                event.correlation_id
            )
        )

    async def work(self) -> None:
        try:
            while not self.should_stop:
                self.heartbeat(f"orchestrator [routed={self.routed_messages} interrupts={self.interruptions}]")
                await asyncio.sleep(1.0)
                
                # Check for inactive conversation timeout (e.g., reset context after 5 mins)
                now = time.perf_counter()
                if now - self._last_activity_time > 300.0 and len(self.context) > 0:
                    self.logger.info("conversation_context_reset_timeout")
                    self.context.clear()
                    self.active_turn_id = None
                    self.active_speaker = None
                    
                # Check response generation timeout (if stuck in routing for too long)
                if self.active_speaker == "assistant" and self._routing_task and not self._routing_task.done():
                    if now - self._last_activity_time > self.response_timeout_seconds:
                        self.logger.warning("conversation_response_timeout", extra={"turn_id": self.active_turn_id})
                        self._routing_task.cancel()
                        self.streaming_worker.cancel_all()
                        
                        if self.active_turn_id:
                            await self.event_bus.publish(
                                Event.create(
                                    EventType.CONVERSATION_TIMEOUT,
                                    {"turn_id": self.active_turn_id, "timeout_type": "routing_timeout"},
                                    self.name
                                )
                            )
                        self.active_speaker = None
                        self._routing_task = None
                        
        except asyncio.CancelledError:
            pass
