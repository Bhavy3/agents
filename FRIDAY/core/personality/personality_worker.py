import asyncio
from ..workers.base_worker import BaseWorker
from ..events.bus import EventBus
from ..events.event_types import EventType
from ..events.models import Event
from .models import PersonaMode, EmotionState
from .style_engine import StyleEngine
from .emotion import EmotionClassifier
from .conversation_profile import ProfileManager


class PersonalityWorker(BaseWorker):
    """Orchestrates personality adaptation and conversational context."""

    def __init__(self, event_bus: EventBus):
        super().__init__("personality_worker", event_bus)
        self.engine = StyleEngine()
        self.classifier = EmotionClassifier()
        self.profiles = ProfileManager()
        
        self.current_mode = PersonaMode.ENGINEERING
        self.last_emotion = EmotionState.CALM
        self.active_tasks_count = 0

    async def run(self) -> None:
        self.event_bus.subscribe(EventType.USER_TEXT_RECEIVED, self.handle_user_input)
        self.event_bus.subscribe(EventType.ACTION_STARTED, self.handle_task_start)
        self.event_bus.subscribe(EventType.ACTION_COMPLETED, self.handle_task_end)
        self.event_bus.subscribe(EventType.ACTION_FAILED, self.handle_task_end)
        await super().run()

    async def work(self) -> None:
        while not self.should_stop:
            self.heartbeat(f"personality [mode={self.current_mode} emotion={self.last_emotion}]")
            await asyncio.sleep(2.0)

    async def handle_user_input(self, event: Event) -> None:
        text = event.payload.get("text", "")
        
        # 1. Classify emotion
        new_emotion = self.classifier.detect_emotion(text, self.last_emotion)
        if new_emotion != self.last_emotion:
            self.last_emotion = new_emotion
            self.logger.info("emotion_changed", extra={"emotion": new_emotion})
            await self.event_bus.publish(Event.create(
                EventType.EMOTION_DETECTED,
                {"emotion": new_emotion.value, "confidence": 1.0},
                self.name,
                event.correlation_id
            ))

        # 2. Compute style
        style = self.engine.compute_style(
            self.current_mode, 
            self.last_emotion, 
            is_task_active=(self.active_tasks_count > 0)
        )

        # 3. Publish personality context
        await self.event_bus.publish(Event.create(
            EventType.PERSONALITY_STYLE_UPDATED,
            {
                "persona_mode": self.current_mode.value,
                "emotion_state": self.last_emotion.value,
                "style_config": {
                    "tone": style.tone,
                    "verbosity": style.verbosity,
                    "pacing": style.pacing,
                    "humor_level": style.humor_level
                }
            },
            self.name,
            event.correlation_id
        ))

    async def handle_task_start(self, event: Event) -> None:
        self.active_tasks_count += 1

    async def handle_task_end(self, event: Event) -> None:
        self.active_tasks_count = max(0, self.active_tasks_count - 1)
