import asyncio
from core.workers.base_worker import BaseWorker
from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.config.settings import load_settings

class TerminalObserverWorker(BaseWorker):
    def __init__(self, event_bus: EventBus):
        super().__init__("terminal_observer", event_bus)
        self.settings = load_settings()
        self._assistant_response = []
        self._should_print = self.settings.console_log_level in ("INFO", "DEBUG")

    def _print(self, text: str):
        if self._should_print:
            print(text, flush=True)

    async def work(self) -> None:
        self.event_bus.subscribe(EventType.SPEECH_STARTED, self._handle_speech_started)
        self.event_bus.subscribe(EventType.SPEECH_ENDED, self._handle_speech_ended)
        self.event_bus.subscribe(EventType.STT_FINAL_TRANSCRIPT, self._handle_stt_final)
        self.event_bus.subscribe(EventType.ASSISTANT_RESPONSE_STARTED, self._handle_response_started)
        self.event_bus.subscribe(EventType.ASSISTANT_RESPONSE_PARTIAL, self._handle_response_partial)
        self.event_bus.subscribe(EventType.ASSISTANT_RESPONSE_COMPLETED, self._handle_response_completed)
        self.event_bus.subscribe(EventType.TTS_PLAYBACK_STARTED, self._handle_tts_started)
        self.event_bus.subscribe(EventType.TTS_PLAYBACK_COMPLETED, self._handle_tts_completed)
        self.event_bus.subscribe(EventType.TTS_PLAYBACK_CANCELLED, self._handle_tts_cancelled)
        try:
            while not self.should_stop:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self.heartbeat("terminal_observer")
        finally:
            subscriptions = (
                (EventType.SPEECH_STARTED, self._handle_speech_started),
                (EventType.SPEECH_ENDED, self._handle_speech_ended),
                (EventType.STT_FINAL_TRANSCRIPT, self._handle_stt_final),
                (EventType.ASSISTANT_RESPONSE_STARTED, self._handle_response_started),
                (EventType.ASSISTANT_RESPONSE_PARTIAL, self._handle_response_partial),
                (EventType.ASSISTANT_RESPONSE_COMPLETED, self._handle_response_completed),
                (EventType.TTS_PLAYBACK_STARTED, self._handle_tts_started),
                (EventType.TTS_PLAYBACK_COMPLETED, self._handle_tts_completed),
                (EventType.TTS_PLAYBACK_CANCELLED, self._handle_tts_cancelled),
            )
            for event_type, handler in subscriptions:
                self.event_bus.unsubscribe(event_type, handler)

    async def _handle_speech_started(self, event: Event) -> None:
        self._print("[USER STARTED SPEAKING]")

    async def _handle_speech_ended(self, event: Event) -> None:
        self._print("[USER STOPPED SPEAKING]")

    async def _handle_stt_final(self, event: Event) -> None:
        text = event.payload.get("text", "")
        self._print(f"[USER HEARD] {text}")

    async def _handle_response_started(self, event: Event) -> None:
        self._assistant_response = []
        self._print("[FRIDAY THINKING]")

    async def _handle_response_partial(self, event: Event) -> None:
        text = event.payload.get("text", "")
        if text:
            self._assistant_response.append(text)

    async def _handle_response_completed(self, event: Event) -> None:
        full_text = event.payload.get("full_text") or event.payload.get("text")
        if not full_text:
            full_text = "".join(self._assistant_response)
        self._print(f"[FRIDAY RESPONSE] {full_text}")

    async def _handle_tts_started(self, event: Event) -> None:
        self._print("[FRIDAY SPEAKING]")

    async def _handle_tts_completed(self, event: Event) -> None:
        self._print("[FRIDAY FINISHED SPEAKING]")

    async def _handle_tts_cancelled(self, event: Event) -> None:
        self._print("[FRIDAY FINISHED SPEAKING]")
