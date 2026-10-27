import asyncio
import inspect
import time
import uuid
from collections import deque
from typing import Any, Optional

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.workers.base_worker import BaseWorker
from core.router.intent_router import IntentRouter
from core.llm.streaming_worker import StreamingLlmWorker
from core.personality.prompt_personality import PersonalityPromptInjector
from core.personality.models import PersonaMode, StyleConfig
from core.personality.presence import PresenceManager
from core.personality.presence_timing import PresenceTimingEngine
from core.router.rules import FAST_CHAT_SOURCE, Intent, IntentName, fast_chat_intent
from core.workflows.prompt_planner import PromptPlanner
from core.orchestrator.response_gate import ResponseReadinessGate
from core.router.complexity_detector import detect_query_complexity
from core.cognition.cognitive_state import CognitiveStateEngine, TurnState
from core.orchestrator.memory_context import (
    MEMORY_CONTEXT_MAX_CHARS,
    MEMORY_QUERY_TIMEOUT_SECONDS,
    MemoryContextMixin,
)
from core.memory.explicit_requests import (
    EXPLICIT_MEMORY_REQUEST as _EXPLICIT_MEMORY_REQUEST,
    PERSONAL_MEMORY_QUERY as _PERSONAL_MEMORY_QUERY,
    extract_explicit_memory_content,
    is_personal_memory_query,
)
from core.orchestrator.workflow_trigger import WorkflowTriggerMixin, _WORKFLOW_REQUEST
from core.orchestrator.web_search import (
    PendingWebSearch,
    WEB_ANSWER_NOT_FOUND,
    WEB_SEARCH_ACK_DELAY_SECONDS,
    WEB_SEARCH_FAILURE_MESSAGE,
    WEB_SEARCH_HISTORY_MAX_CHARS,
    WEB_SEARCH_QUERY_MAX_CHARS,
    WEB_SEARCH_RESULTS_MAX_CHARS,
    WebSearchMixin,
    ground_web_answer,
)

DEGRADED_ROUTER_MESSAGE = "I'm unable to reach the conversation router right now. Please try again."
class OrchestratorWorker(BaseWorker, WebSearchMixin, MemoryContextMixin, WorkflowTriggerMixin):
    """Coordinates conversation turns, routing, and interruptions."""

    def __init__(
        self,
        event_bus: EventBus,
        intent_router: IntentRouter | None,
        streaming_worker: StreamingLlmWorker,
        prompt_planner: Optional[PromptPlanner] = None,
        max_context_turns: int = 5,
        response_timeout_seconds: float = 30.0,
        interrupt_cooldown_seconds: float = 1.5,
        enable_presence_ack: bool = False,
        cognitive_state: CognitiveStateEngine | None = None,
        state_engine: CognitiveStateEngine | None = None,
        model_manager: object | None = None,
    ) -> None:
        super().__init__("orchestrator", event_bus)
        self.intent_router = intent_router
        self.streaming_worker = streaming_worker
        if self.intent_router is None:
            self.logger.warning("orchestrator_missing_router_falling_back_to_chat")
        self.prompt_planner = prompt_planner
        self.max_context_turns = max_context_turns
        self.response_timeout_seconds = response_timeout_seconds
        self.interrupt_cooldown_seconds = interrupt_cooldown_seconds
        self.enable_presence_ack = enable_presence_ack
        self.injector = PersonalityPromptInjector()
        self.presence = PresenceManager()
        self.presence_timing = PresenceTimingEngine(event_bus)
        self.response_gate = ResponseReadinessGate(event_bus, self.presence_timing)
        self.response_timeout = 10  # seconds
        from core.router.adaptive_router import AdaptiveRouter
        # The streaming worker is the sole owner of the active request model.
        # The legacy ModelManager remains available to its direct callers, but
        # ordinary routing must not launch a second llama-server process.
        self.adaptive_router = AdaptiveRouter(model_manager=model_manager)
        if cognitive_state is not None and state_engine is not None and cognitive_state is not state_engine:
            raise ValueError("cognitive_state and state_engine must reference the same engine")
        self.cognitive_state = cognitive_state or state_engine or CognitiveStateEngine(event_bus)
        # Keep the explicit name available to callers while retaining the
        # historical cognitive_state attribute used by the orchestrator.
        self.state_engine = self.cognitive_state
        
        self._state_lock = asyncio.Lock()
        self.active_turn_id: str | None = None
        self._pending_web_searches: dict[str, PendingWebSearch] = {}
        self._web_search_ack_tasks: dict[str, asyncio.Task[None]] = {}
        self._web_search_answer_tasks: dict[str, asyncio.Task[None]] = {}
        self._turn_ids_by_correlation_id: dict[str, str] = {}
        self._init_memory_context()
        self.current_mode = PersonaMode.ENGINEERING
        self.current_style = StyleConfig(tone="focused", verbosity="concise", pacing="normal")
        self.active_speaker: str | None = None
        self.context: list[dict[str, str]] = []
        self._routing_task: asyncio.Task | None = None
        self._turn_start_pending = False
        self._queued_cli_turns: deque[tuple[str, str | None]] = deque()
        self._pending_workflow_correlations: set[str] = set()
        self._last_activity_time = time.perf_counter()
        
        self._chat_confirmed = False
        self._chunk_buffer: list[str] = []
        
        # Interrupt storm protection
        self._interrupt_cooldown_until = 0.0

        # Stats
        self.active_conversations = 0
        self.interruptions = 0
        self.stale_drops = 0
        self.total_latency = 0.0
        self.routed_messages = 0

    async def run(self) -> None:
        self.event_bus.subscribe(EventType.STT_FINAL_TRANSCRIPT, self._handle_final_transcript)
        self.event_bus.subscribe(EventType.SPEECH_STARTED, self._handle_speech_started)
        self.event_bus.subscribe(EventType.USER_SPEECH, self._handle_user_speech)

        # Map LLM Stream events to Conversation events
        self.event_bus.subscribe(EventType.STREAM_STARTED, self._handle_stream_started)
        self.event_bus.subscribe(EventType.STREAM_CHUNK, self._handle_stream_chunk)
        self.event_bus.subscribe(EventType.STREAM_COMPLETED, self._handle_stream_completed)
        self.event_bus.subscribe(EventType.STREAM_CANCELLED, self._handle_stream_cancelled)
        self.event_bus.subscribe(EventType.STREAM_TIMEOUT, self._handle_stream_timeout)
        
        # Audio physical playback state resets
        self.event_bus.subscribe(EventType.TTS_PLAYBACK_COMPLETED, self._handle_tts_playback_completed)
        self.event_bus.subscribe(EventType.TTS_PLAYBACK_CANCELLED, self._handle_tts_playback_cancelled)

        # Handle CLI fallback if needed (Command console input bypasses STT)
        self.event_bus.subscribe(EventType.USER_TEXT_RECEIVED, self._handle_cli_text)
        
        # Personality updates
        self.event_bus.subscribe(EventType.PERSONALITY_STYLE_UPDATED, self._handle_personality_update)
        self.event_bus.subscribe(EventType.MEMORY_CONTEXT_READY, self._handle_memory_context)
        self.event_bus.subscribe(EventType.MEMORY_QUERY_RESULT, self._handle_memory_query_result)
        self.event_bus.subscribe(EventType.MEMORY_FAILURE, self._handle_memory_failure)
        self.event_bus.subscribe(EventType.ACTION_COMPLETED, self._handle_web_search_completed)
        self.event_bus.subscribe(EventType.ACTION_FAILED, self._handle_web_search_failed)
        self.event_bus.subscribe(EventType.ACTION_TIMEOUT, self._handle_web_search_timeout)
        self.event_bus.subscribe(EventType.CONVERSATION_INTERRUPTED, self._handle_web_search_interrupted)
        self.event_bus.subscribe(EventType.ACTION_GRAPH_COMPLETED, self._handle_workflow_terminal)
        self.event_bus.subscribe(EventType.ACTION_GRAPH_FAILED, self._handle_workflow_terminal)
        await super().run()

    async def stop(self) -> None:
        """Cancel turn-owned background work before the shared client closes."""
        tasks = list(self._web_search_answer_tasks.values())
        tasks.extend(self._web_search_ack_tasks.values())
        if self._routing_task is not None:
            tasks.append(self._routing_task)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._web_search_answer_tasks.clear()
        self._web_search_ack_tasks.clear()
        self._routing_task = None
        await super().stop()

    async def _handle_workflow_terminal(self, event: Event) -> None:
        correlation_id = event.correlation_id or ""
        if correlation_id not in self._pending_workflow_correlations:
            return
        self._pending_workflow_correlations.discard(correlation_id)
        async with self._state_lock:
            turn_id = self._turn_ids_by_correlation_id.get(correlation_id)
            if turn_id and self.active_turn_id == turn_id:
                self.active_turn_id = None
                self.active_speaker = None
                self._routing_task = None
        await self._start_next_cli_turn()

    async def _start_next_cli_turn(self) -> None:
        async with self._state_lock:
            if (
                self._turn_start_pending
                or self.active_turn_id is not None
                or self.active_speaker is not None
                or not self._queued_cli_turns
            ):
                return
            text, correlation_id = self._queued_cli_turns.popleft()
            self._turn_start_pending = True
        asyncio.create_task(self._initiate_turn(text, correlation_id, typed_input=True))








    async def _publish_assistant_lifecycle(self, event: Event) -> bool:
        """Apply a response lifecycle transition before queueing its event."""
        if not await self.cognitive_state.apply_event(event):
            return False
        await self.event_bus.publish(event)
        return True







    async def _handle_speech_started(self, event: Event) -> bool:
        """User started speaking; return whether a new turn may be started."""
        now = time.perf_counter()
        self._last_activity_time = now
        
        async with self._state_lock:
            if self._turn_start_pending and self.active_turn_id is None:
                return False
            pending_search = any(
                pending.turn_id == self.active_turn_id
                for pending in self._pending_web_searches.values()
            )
            is_interruption = (
                self.active_speaker == "assistant"
                or self._routing_task is not None
                or pending_search
                or self.response_gate.has_pending(self.active_turn_id)
                or (self._turn_start_pending and self.active_turn_id is not None)
            )
            
            if is_interruption:
                # Interrupt storm debounce
                if now < self._interrupt_cooldown_until:
                    return False
                    
                self._interrupt_cooldown_until = now + self.interrupt_cooldown_seconds
                self.interruptions += 1
                
                # Capture values to cancel outside lock
                routing_task_to_cancel = self._routing_task
                turn_id_to_interrupt = self.active_turn_id
                if turn_id_to_interrupt:
                    self._turn_ids_by_correlation_id = {
                        correlation_id: turn_id
                        for correlation_id, turn_id in self._turn_ids_by_correlation_id.items()
                        if turn_id != turn_id_to_interrupt
                    }
                
                self._routing_task = None
                self._turn_start_pending = False
                if self._routing_task is None and self.active_turn_id == turn_id_to_interrupt:
                    self.active_turn_id = None
            else:
                routing_task_to_cancel = None
                turn_id_to_interrupt = None
                
            self.active_speaker = "user"

        # The orchestrator owns the live user-speech transition.  STT/CLI
        # callers reuse this path, so normalize those legacy triggers to the
        # same canonical state transition without emitting a second event.
        state_event = event
        if event.event_type not in {EventType.SPEECH_STARTED, EventType.USER_SPEECH}:
            state_event = Event.create(
                EventType.USER_SPEECH,
                {"status": "started"},
                self.name,
                event.correlation_id,
            )
        await self.cognitive_state.apply_event(state_event)
        
        if is_interruption:
            self.logger.info("conversation_interrupted", extra={"turn_id": turn_id_to_interrupt})
            
            # Cancel active routing/inference
            self.response_gate.cancel_wait(turn_id_to_interrupt)
            if routing_task_to_cancel and not routing_task_to_cancel.done():
                routing_task_to_cancel.cancel()
            self.streaming_worker.cancel_all()
            
            if turn_id_to_interrupt:
                await self.event_bus.publish(
                    Event.create(
                        EventType.CONVERSATION_INTERRUPTED,
                        {"turn_id": turn_id_to_interrupt, "reason": "user_interruption"},
                        self.name
                    )
                )
        return True

    async def _handle_user_speech(self, event: Event) -> None:
        """Handle user speech events to keep active speaker aligned."""
        status = event.payload.get("status")
        if status == "started":
            await self._handle_speech_started(event)

    async def _handle_final_transcript(self, event: Event) -> None:
        """Process finalized text from STT."""
        self.logger.info(f"ORCHESTRATOR_RECEIVED_FINAL_TRANSCRIPT text='{event.payload.get('text', '')}'")
        text = event.payload.get("text", "").strip()
        if not text:
            return
            
        if await self._handle_speech_started(event):
            await self._schedule_turn(text, event.correlation_id, voice_input=True)

    async def _handle_cli_text(self, event: Event) -> None:
        """Process text directly from CLI."""
        text = event.payload.get("text", "").strip()
        if not text:
            return

        async with self._state_lock:
            self._queued_cli_turns.append((text, event.correlation_id))
        await self._start_next_cli_turn()

    async def _schedule_turn(
        self,
        text: str,
        correlation_id: str | None,
        *,
        voice_input: bool = False,
    ) -> None:
        async with self._state_lock:
            if self._turn_start_pending:
                return
            self._turn_start_pending = True
        asyncio.create_task(self._initiate_turn(text, correlation_id, voice_input=voice_input))

    async def _initiate_turn(
        self,
        text: str,
        correlation_id: str | None,
        *,
        voice_input: bool = False,
        typed_input: bool = False,
    ) -> None:
        correlation_id = correlation_id or str(uuid.uuid4())
        self._last_activity_time = time.perf_counter()
        memory_content = extract_explicit_memory_content(text)
        
        async with self._state_lock:
            turn_id = str(uuid.uuid4())[:8]
            self.active_turn_id = turn_id
            self._turn_ids_by_correlation_id = {correlation_id: turn_id}
            self.active_speaker = "user"
            self._chat_confirmed = False
            self._chunk_buffer.clear()
            
            # Append to context
            self.context.append({"role": "user", "content": text})
            if len(self.context) > self.max_context_turns * 2:
                self.context = self.context[-(self.max_context_turns * 2):]
        
        turn_started = Event.create(
            EventType.CONVERSATION_TURN_STARTED,
            {"turn_id": turn_id, "speaker": "user"},
            self.name,
            correlation_id,
        )
        await self.cognitive_state.apply_event(turn_started)
        await self.event_bus.publish(turn_started)
        
        await self.event_bus.publish(
            Event.create(
                EventType.USER_MESSAGE_RECEIVED,
                {"turn_id": turn_id, "text": text},
                self.name,
                correlation_id
            )
        )

        if memory_content:
            await self.event_bus.publish(Event.create(
                EventType.MEMORY_WRITE_REQUEST,
                {
                    "type": "approved_fact",
                    "content": memory_content,
                    "source": "explicit_user_request",
                    "explicit_user_approved": True,
                },
                self.name,
                correlation_id,
            ))
        
        # Human presence: Acknowledgment
        ack = self.presence.get_acknowledgment(self.current_style, self.enable_presence_ack)
        if ack:
            await self.event_bus.publish(
                Event.create(
                    EventType.ASSISTANT_RESPONSE_PARTIAL,
                    {"turn_id": turn_id, "text": ack + " "},
                    self.name,
                    correlation_id
                )
            )

        # Tone modulation: update tone before querying LLM
        recent_turns = [turn["content"] for turn in self.context[:-1]]
        await self.cognitive_state.update_tone(text, history=recent_turns)
        # Snapshot delivery context for this turn.  Routing is scheduled below
        # and may overlap a later turn that changes the shared cognitive tone.
        tone_context = self.cognitive_state.get_tone_context()

        selected_model, selection_reason = await self.adaptive_router.route(text)
        selector = getattr(self.streaming_worker, "set_model", None)
        if callable(selector):
            selection_result = selector(selected_model, selection_reason)
            if inspect.isawaitable(selection_result):
                await selection_result

        owns_turn = False
        async with self._state_lock:
            if self.active_turn_id == turn_id:
                self._turn_start_pending = False
                # Yield to assistant
                self.active_speaker = "assistant"
                owns_turn = True
                
                # Spawn routing task so Orchestrator remains unblocked
                self._routing_task = asyncio.create_task(
                    self._route_and_execute(
                        text,
                        turn_id,
                        correlation_id,
                        voice_input=voice_input,
                        typed_input=typed_input,
                        tone_context=tone_context,
                    )
                )

        if owns_turn:
            # Keep the shared authority aligned during routing, before the
            # stream-start event makes the assistant physically speak.
            await self.cognitive_state.update_state(
                active_turn_id=turn_id,
                active_speaker="assistant",
                turn_state=TurnState.THINKING,
                assistant_busy=True,
                speaking=False,
                listening=False,
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

    async def _route_and_execute(
        self,
        text: str,
        turn_id: str,
        correlation_id: str | None,
        *,
        voice_input: bool = False,
        typed_input: bool = False,
        tone_context: str | None = None,
    ) -> None:
        start_time = time.perf_counter()
        deferred_web_search: str | None = None
        try:
            if voice_input:
                ready = await self.response_gate.wait_for_readiness(
                    turn_id,
                    text_length=len(text),
                    momentum=0.0,
                )
                if not ready:
                    return

            if extract_explicit_memory_content(text) is not None:
                response_text = "I'll remember that."
                async with self._state_lock:
                    if self.active_turn_id == turn_id:
                        self.context.append({"role": "assistant", "content": response_text})
                await self._publish_direct_response(response_text, turn_id, correlation_id)
                await self.event_bus.publish(Event.create(
                    EventType.RESPONSE_READY,
                    {"text": response_text, "turn_id": turn_id},
                    self.name,
                    correlation_id,
                ))
                await self.event_bus.publish(Event.create(
                    EventType.CONVERSATION_TURN_ENDED,
                    {"turn_id": turn_id, "duration": round(time.perf_counter() - start_time, 3)},
                    self.name,
                    correlation_id,
                ))
                return

            fast_intent = fast_chat_intent(text) if typed_input else None

            # Generate personality instructions
            base_instructions = self.injector.get_style_instructions(self.current_style, self.current_mode)
            tone_ctx = tone_context if tone_context is not None else self.cognitive_state.get_tone_context()
            if tone_ctx:
                delivery_instructions = f"{tone_ctx}\n\n{base_instructions}"
            else:
                delivery_instructions = base_instructions
            # General chat has no explicit memory or action signal. Avoid a
            # serialized memory round-trip on this latency-sensitive path;
            # memory-bearing and dynamic requests retain the normal lookup.
            mem_ctx = "" if fast_intent is not None else await self._request_memory_context(text)
                
            # Emotional context may shape the answer, but must not steer the
            # intent classifier's choice of tools or actions.
            router_instructions = base_instructions
            chat_instructions = delivery_instructions
            if mem_ctx:
                chat_instructions += f"\n\nSystem Memory/Context:\n{mem_ctx}"

            personal_memory = next(
                (line.removeprefix("- ").strip() for line in mem_ctx.splitlines() if line.strip()),
                "",
            )
            if fast_intent is not None:
                intent = fast_intent
            elif is_personal_memory_query(text) and personal_memory:
                intent = Intent(
                    IntentName.CHAT,
                    1.0,
                    {"response_text": f"You told me: {personal_memory}"},
                    source="personal_memory",
                )
            else:
                intent = None

            if intent is None and await self._try_start_workflow(text, turn_id, correlation_id, start_time):
                return

            # Otherwise, proceed with simple routing. If memory had no relevant
            # personal fact, the normal router can still choose web search.
            if intent is None:
                if self.intent_router is not None:
                    try:
                        intent = await self.intent_router.route(
                            text,
                            context=self.context,
                            correlation_id=correlation_id,
                            personality_instructions=router_instructions,
                            chat_instructions=chat_instructions,
                        )
                    except Exception:
                        self.logger.exception("intent_router_route_failed", extra={"turn_id": turn_id})
                        intent = None

            if intent is None:
                self.routed_messages += 1
                async with self._state_lock:
                    if self.active_turn_id == turn_id:
                        self.context.append({"role": "assistant", "content": DEGRADED_ROUTER_MESSAGE})
                await self.event_bus.publish(
                    Event.create(
                        EventType.RESPONSE_READY,
                        {"text": DEGRADED_ROUTER_MESSAGE, "turn_id": turn_id},
                        self.name,
                        correlation_id,
                    )
                )
                return

            self.routed_messages += 1

            if intent.name.value == "chat":
                async with self._state_lock:
                    self._chat_confirmed = True
                    # Flush speculative chunk buffer
                    chunk_buffer = list(self._chunk_buffer)
                    self._chunk_buffer.clear()

                for chunk in chunk_buffer:
                    await self.event_bus.publish(
                        Event.create(
                            EventType.ASSISTANT_RESPONSE_PARTIAL,
                            {"turn_id": turn_id, "text": chunk},
                            self.name,
                            correlation_id,
                        )
                    )

                # A fast-chat intent has already passed the conservative local
                # classifier.  Stream it directly instead of asking the LLM to
                # classify it and then asking the same LLM to answer it.
                if intent.source == FAST_CHAT_SOURCE:
                    response_text = await self.streaming_worker.stream_reasoning(
                        self._build_fast_chat_prompt(text, tone_ctx),
                        correlation_id,
                    )
                else:
                    response_text = intent.parameters.get("response_text", intent.parameters.get("text", ""))
                if response_text:
                    async with self._state_lock:
                        if self.active_turn_id == turn_id:
                            self.context.append({"role": "assistant", "content": response_text})
                    if intent.source not in {"ollama_reasoning", FAST_CHAT_SOURCE}:
                        await self._publish_direct_response(response_text, turn_id, correlation_id)
                    await self.event_bus.publish(
                        Event.create(
                            EventType.RESPONSE_READY,
                            {"text": response_text, "turn_id": turn_id},
                            self.name,
                            correlation_id,
                        )
                    )
            else:
                async with self._state_lock:
                    self._chunk_buffer.clear()
                action_id = str(uuid.uuid4())
                action_correlation_id = correlation_id or str(uuid.uuid4())
                if intent.name in {IntentName.SEARCH_WEB, IntentName.RESEARCH_WEB, IntentName.OPEN_SECTION}:
                    deferred_web_search = action_correlation_id
                    pending_query = str(
                        intent.parameters.get(
                            "query",
                            intent.parameters.get("section", text),
                        )
                    )
                    self._pending_web_searches[action_correlation_id] = PendingWebSearch(
                        query=pending_query,
                        user_text=text,
                        turn_id=turn_id,
                        personality_instructions=delivery_instructions,
                        memory_context=mem_ctx,
                        tool_name=intent.name.value,
                    )
                    self._web_search_ack_tasks[action_correlation_id] = asyncio.create_task(
                        self._announce_web_search_if_slow(action_correlation_id, turn_id),
                        name=f"web-search-ack-{turn_id}",
                    )
                await self.event_bus.publish(
                    Event.create(
                        EventType.ACTION_REQUESTED,
                        {
                            "action_id": action_id,
                            "intent": intent.name.value,
                            "parameters": intent.parameters,
                        },
                        self.name,
                        action_correlation_id,
                    )
                )
            
            # If the routing finishes successfully
            duration = time.perf_counter() - start_time
            if deferred_web_search is None:
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
        except Exception:
            self.logger.exception("routing_failed", extra={"turn_id": turn_id})
            if deferred_web_search is not None:
                self._pending_web_searches.pop(deferred_web_search, None)
                await self._cancel_web_search_ack(deferred_web_search)
        finally:
            start_next_cli_turn = False
            async with self._state_lock:
                if self.active_turn_id == turn_id:
                    self._routing_task = None
                    workflow_pending = correlation_id in self._pending_workflow_correlations
                    if deferred_web_search not in self._pending_web_searches and not workflow_pending:
                        self.active_turn_id = None
                        if self.active_speaker == "assistant":
                            self.active_speaker = None
                        start_next_cli_turn = True
            if start_next_cli_turn:
                await self._start_next_cli_turn()

    @staticmethod
    def _build_chat_prompt(
        text: str,
        context: list[dict[str, str]],
        chat_instructions: str,
    ) -> str:
        """Build the normal chat prompt without adding a second classifier call."""
        context_str = chat_instructions + "\n\n" if chat_instructions else ""
        history_str = "\n".join(
            f"{item['role'].capitalize()}: {item['content']}"
            for item in context[:-1]
        )
        if history_str:
            context_str += f"{history_str}\nUser: {text}\nResponse:"
        else:
            context_str += f"User: {text}\nResponse:"
        return context_str.strip()

    @staticmethod
    def _build_fast_chat_prompt(text: str, tone_context: str | None) -> str:
        """Build a compact typed-chat prompt to reduce first-token latency."""
        tone = f"{tone_context}\n\n" if tone_context else ""
        return (
            f"{tone}Answer accurately and concisely. Do not claim to remember information "
            "unless the user explicitly asks you to remember it.\n"
            f"User: {text}\nResponse:"
        ).strip()

    async def _publish_direct_response(
        self,
        text: str,
        turn_id: str,
        correlation_id: str | None,
    ) -> None:
        await self._publish_assistant_lifecycle(
            Event.create(
                EventType.ASSISTANT_RESPONSE_STARTED,
                {"turn_id": turn_id},
                self.name,
                correlation_id,
            )
        )
        await self.event_bus.publish(Event.create(
            EventType.ASSISTANT_RESPONSE_PARTIAL,
            {"turn_id": turn_id, "text": text},
            self.name,
            correlation_id,
        ))
        await self._publish_assistant_lifecycle(
            Event.create(
                EventType.ASSISTANT_RESPONSE_COMPLETED,
                {"turn_id": turn_id, "text": text},
                self.name,
                correlation_id,
            )
        )

    # Translating LLM Stream Events to Conversation Events
    async def _handle_stream_started(self, event: Event) -> None:
        async with self._state_lock:
            turn_id = self._turn_ids_by_correlation_id.get(event.correlation_id or "")
            if turn_id is None:
                return
            
        await self._publish_assistant_lifecycle(
            Event.create(
                EventType.ASSISTANT_RESPONSE_STARTED,
                {"turn_id": turn_id},
                self.name,
                event.correlation_id,
            )
        )

    async def _handle_stream_chunk(self, event: Event) -> None:
        async with self._state_lock:
            turn_id = self._turn_ids_by_correlation_id.get(event.correlation_id or "")
            if turn_id is None:
                return
            chat_confirmed = self._chat_confirmed
            
        chunk = event.payload.get("chunk", "")
        if chat_confirmed:
            await self.event_bus.publish(
                Event.create(
                    EventType.ASSISTANT_RESPONSE_PARTIAL,
                    {"turn_id": turn_id, "text": chunk},
                    self.name,
                    event.correlation_id
                )
            )
        else:
            async with self._state_lock:
                if self.active_speaker == "assistant" and self.active_turn_id == turn_id:
                    self._chunk_buffer.append(chunk)

    async def _handle_stream_completed(self, event: Event) -> None:
        turn_released = False
        async with self._state_lock:
            turn_id = self._turn_ids_by_correlation_id.get(event.correlation_id or "")
            if turn_id is None:
                return
            routing_task = self._routing_task

        # Ensure routing task finishes and flushes speculative chunks before signaling completion
        if routing_task and not routing_task.done():
            try:
                await asyncio.shield(routing_task)
            except Exception as e:
                self.logger.error("routing_task_await_failed_in_stream_completed", extra={"error": str(e)})

        async with self._state_lock:
            if self._turn_ids_by_correlation_id.get(event.correlation_id or "") != turn_id:
                return
            full_text = event.payload.get("full_text", "")
            if self.active_turn_id == turn_id:
                self.context.append({"role": "assistant", "content": full_text})
            if self.active_turn_id == turn_id:
                self.active_speaker = None
                pending_web_search = self._pending_web_searches.get(event.correlation_id)
                if pending_web_search is not None and pending_web_search.turn_id == turn_id:
                    self._pending_web_searches.pop(event.correlation_id, None)
                    self.active_turn_id = None
                    self._routing_task = None
                    turn_released = True
            self._turn_ids_by_correlation_id.pop(event.correlation_id or "", None)
            
        await self._publish_assistant_lifecycle(
            Event.create(
                EventType.ASSISTANT_RESPONSE_COMPLETED,
                {"turn_id": turn_id, "text": full_text},
                self.name,
                event.correlation_id,
            )
        )
        if turn_released:
            await self._start_next_cli_turn()

    async def _handle_stream_cancelled(self, event: Event) -> None:
        async with self._state_lock:
            turn_id = self._turn_ids_by_correlation_id.pop(event.correlation_id or "", None)
            if turn_id is None:
                return
            if self.active_turn_id == turn_id:
                self.active_speaker = None
            
        await self._publish_assistant_lifecycle(
            Event.create(
                EventType.ASSISTANT_RESPONSE_CANCELLED,
                {"turn_id": turn_id, "reason": event.payload.get("reason", "unknown")},
                self.name,
                event.correlation_id,
            )
        )

    async def _handle_stream_timeout(self, event: Event) -> None:
        async with self._state_lock:
            if self.active_speaker != "assistant":
                return
            turn_id = self.active_turn_id
            self.active_speaker = None
            
        await self.event_bus.publish(
            Event.create(
                EventType.CONVERSATION_TIMEOUT,
                {"turn_id": turn_id, "timeout_type": event.payload.get("timeout_type", "unknown")},
                self.name,
                event.correlation_id
            )
        )

    # Physical TTS Playback State Handlers
    async def _handle_tts_playback_completed(self, event: Event) -> None:
        async with self._state_lock:
            # We only reset active_speaker to allow clean turn transitions.
            # We DO NOT cancel _routing_task here. A single LLM response can span multiple sentences.
            # If the LLM is slow (> 2.5s gap), physical audio might temporarily finish, firing COMPLETED.
            # Cancelling the routing task here would truncate the response mid-generation.
            if self.active_turn_id == event.payload.get("turn_id"):
                self.active_speaker = "user"

    async def _handle_tts_playback_cancelled(self, event: Event) -> None:
        async with self._state_lock:
            # We don't cancel _routing_task here either, as _handle_speech_started
            # already cancels it upon detecting the interruption that caused this cancel.
            if self.active_turn_id == event.payload.get("turn_id"):
                self.active_speaker = "user"


    async def work(self) -> None:
        try:
            while not self.should_stop:
                self.heartbeat(f"orchestrator [routed={self.routed_messages} interrupts={self.interruptions}]")
                await asyncio.sleep(1.0)
                
                # Check for inactive conversation timeout (e.g., reset context after 5 mins)
                now = time.perf_counter()
                async with self._state_lock:
                    if now - self._last_activity_time > 300.0 and len(self.context) > 0:
                        self.logger.info("conversation_context_reset_timeout")
                        self.context.clear()
                        self.active_turn_id = None
                        self.active_speaker = None
                        
                    # Check response generation timeout (if stuck in routing for too long)
                    if self.active_speaker == "assistant" and self._routing_task and not self._routing_task.done():
                        if now - self._last_activity_time > self.response_timeout_seconds:
                            turn_id_to_timeout = self.active_turn_id
                            routing_task_to_cancel = self._routing_task
                            
                            self._routing_task = None
                            self.active_speaker = None
                        else:
                            turn_id_to_timeout = None
                            routing_task_to_cancel = None
                    else:
                        turn_id_to_timeout = None
                        routing_task_to_cancel = None
                        
                if routing_task_to_cancel:
                    self.logger.warning("conversation_response_timeout", extra={"turn_id": turn_id_to_timeout})
                    routing_task_to_cancel.cancel()
                    self.streaming_worker.cancel_all()
                    
                    if turn_id_to_timeout:
                        await self.event_bus.publish(
                            Event.create(
                                EventType.CONVERSATION_TIMEOUT,
                                {"turn_id": turn_id_to_timeout, "timeout_type": "routing_timeout"},
                                self.name
                            )
                        )
                        
        except asyncio.CancelledError:
            self.logger.info("workflow_timeout_monitor_stopped")
