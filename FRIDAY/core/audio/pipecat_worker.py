import asyncio
import time
import uuid

try:
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.task import PipelineTask
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
    from pipecat.services.whisper.stt import WhisperSTTService
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.audio.vad.vad_analyzer import VADParams
    from pipecat.processors.audio.vad_processor import VADProcessor
    from pipecat.processors.frame_processor import FrameProcessor
    from pipecat.frames.frames import TranscriptionFrame, AudioRawFrame
except ImportError:
    pass  # Allow tests to mock

from core.events.bus import EventBus
from core.events.event_types import EventType
from core.events.models import Event
from core.workers.base_worker import BaseWorker
from core.config.settings import load_settings

class MuteGateProcessor(FrameProcessor):
    def __init__(self, worker: 'PipecatAudioWorker'):
        super().__init__()
        self.worker = worker

    async def process_frame(self, frame, direction):
        if type(frame).__name__ == 'AudioRawFrame':
            if self.worker.is_tts_playing:
                muted_audio = b'\x00' * len(frame.audio)
                frame = AudioRawFrame(
                    audio=muted_audio,
                    sample_rate=frame.sample_rate,
                    num_channels=frame.num_channels
                )
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

class TranscriptionPublisher(FrameProcessor):
    def __init__(self, worker: 'PipecatAudioWorker'):
        super().__init__()
        self.worker = worker
        self.event_bus = worker.event_bus
        self.logger = worker.logger
        self.segment_start_time = time.perf_counter()

    async def process_frame(self, frame, direction):
        frame_type = type(frame).__name__
        if frame_type not in ('AudioRawFrame', 'InputAudioRawFrame', 'OutputAudioRawFrame', 'SystemFrame', 'MetricsFrame', 'UserSpeakingFrame'):
            print(f"RAW DIAGNOSTIC: TranscriptionPublisher.process_frame CALLED with frame type {frame_type}")
            if frame_type == 'TranscriptionFrame':
                print(f"RAW DIAGNOSTIC: TranscriptionFrame received! text='{frame.text}'")
            self.logger.info("pipecat_frame_received_trace", extra={"frame_type": frame_type})
        
        if frame_type in ('UserStartedSpeakingFrame', 'VADUserStartedSpeakingFrame'):
            payload = {"timestamp": time.time(), "amplitude": 1.0}
            await self.event_bus.publish(Event.create(EventType.SPEECH_STARTED, payload, "PipecatAudioWorker"))
            
        if type(frame).__name__ == 'TranscriptionFrame':
            self.logger.info("pipecat_transcription_frame_received", extra={"text": frame.text, "is_empty": not bool(frame.text.strip())})
            
            text = frame.text.strip()
            if text:
                import re
                clean_transcription = re.sub(r'[^\w\s]', '', text.lower()).strip()
                clean_spoken = re.sub(r'[^\w\s]', '', self.worker.last_spoken_text).strip()
                time_since_speech = time.time() - self.worker.last_spoken_time
                
                if time_since_speech < (self.worker.mute_gate_delay + 3.0) and clean_spoken:
                    if len(clean_transcription) > 3 and clean_transcription in clean_spoken:
                        self.logger.warning(f"MUTE GATE CAUGHT SELF-FEEDBACK: '{text}' matched recent TTS output")
                        print(f"\n\n[DIAGNOSTIC] MUTE GATE CAUGHT SELF-FEEDBACK: '{text}'\n\n")
                        return

                segment_id = f"pipecat-{uuid.uuid4().hex[:8]}"
                duration = time.perf_counter() - self.segment_start_time
                
                payload = {
                    "segment_id": segment_id,
                    "text": frame.text.strip(),
                    "duration": float(duration),
                    "confidence": 1.0
                }
                
                print(f"RAW DIAGNOSTIC: Payload prepared: {payload}")
                self.logger.info("pipecat_stt_final", extra={"text": payload["text"], "duration": duration})
                
                try:
                    print(f"RAW DIAGNOSTIC: ABOUT TO CALL event_bus.publish({EventType.STT_FINAL_TRANSCRIPT})")
                    self.logger.info("pipecat_publish_attempt", extra={
                        "event_type": str(EventType.STT_FINAL_TRANSCRIPT),
                        "payload": payload
                    })
                    await self.event_bus.publish(
                        Event.create(
                            EventType.STT_FINAL_TRANSCRIPT,
                            payload,
                            "PipecatAudioWorker"
                        )
                    )
                    print(f"RAW DIAGNOSTIC: SUCCESSFULLY CALLED event_bus.publish")
                    self.logger.info("pipecat_publish_success")
                except Exception as e:
                    import traceback
                    print(f"RAW DIAGNOSTIC: EXCEPTION CAUGHT DURING PUBLISH:")
                    traceback.print_exc()
                    self.logger.error("pipecat_publish_error", extra={"error": str(e)}, exc_info=True)
                
                self.segment_start_time = time.perf_counter()
        
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

class PipecatAudioWorker(BaseWorker):
    def __init__(self, event_bus: EventBus):
        super().__init__("pipecat_audio", event_bus)
        self.is_tts_playing = False
        self._lock = asyncio.Lock()
        self.last_spoken_text = ""
        self.last_spoken_time = 0.0
        
        settings = load_settings()
        self.mute_gate_delay = getattr(settings, "mute_gate_delay", 0.6)

    async def run(self) -> None:
        self.event_bus.subscribe(EventType.TTS_PLAYBACK_STARTED, self._handle_tts_started)
        self.event_bus.subscribe(EventType.TTS_PLAYBACK_COMPLETED, self._handle_tts_completed)
        self.event_bus.subscribe(EventType.RESPONSE_READY, self._handle_response_ready)
        await super().run()

    async def _handle_response_ready(self, event: Event) -> None:
        text = event.payload.get("text", "")
        if text:
            async with self._lock:
                self.last_spoken_text = text.lower()
                self.last_spoken_time = time.time()

    async def _handle_tts_started(self, event: Event) -> None:
        async with self._lock:
            self.is_tts_playing = True

    async def _handle_tts_completed(self, event: Event) -> None:
        asyncio.create_task(self._delayed_unmute(self.mute_gate_delay))

    async def _delayed_unmute(self, delay: float) -> None:
        await asyncio.sleep(delay)
        async with self._lock:
            self.is_tts_playing = False
            self.last_spoken_time = time.time()

    async def work(self) -> None:
        self.logger.info("pipecat_worker_starting", extra={"detail": "Starting Pipecat Audio Worker"})
        
        transport = LocalAudioTransport(
            LocalAudioTransportParams(
                audio_in_enabled=True,
                audio_out_enabled=False
            )
        )

        stt = WhisperSTTService(
            device="cpu",
            compute_type="int8",
            settings=WhisperSTTService.Settings(
                model="tiny"
            )
        )

        settings = load_settings()
        vad_stop_secs = getattr(settings, "vad_stop_secs", 0.8)
        self.logger.info("vad_config", extra={"stop_secs": vad_stop_secs})
        vad = SileroVADAnalyzer(params=VADParams(stop_secs=vad_stop_secs))
        vad_processor = VADProcessor(vad_analyzer=vad)

        pipeline = Pipeline([
            transport.input(),
            MuteGateProcessor(self),
            vad_processor,
            stt,
            TranscriptionPublisher(self),
            transport.output()
        ])

        task = PipelineTask(pipeline)
        runner = PipelineRunner()
        
        self.logger.info("pipecat_pipeline_ready", extra={"detail": "Pipecat Pipeline defined, starting runner"})
        
        runner_task = asyncio.create_task(runner.run(task))
        
        while not self.should_stop:
            self.heartbeat("running pipeline")
            done, _ = await asyncio.wait([runner_task], timeout=1.0, return_when=asyncio.FIRST_COMPLETED)
            if runner_task in done:
                break
                
        if self.should_stop and not runner_task.done():
            self.logger.info("pipecat_worker_stopping", extra={"detail": "Worker stopping, cancelling Pipecat task"})
            task.cancel()
            await runner_task
