import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger("core.llm.llm_worker")


class LlmWorker:
    """Manages LLM inference with timeout-triggered model escalation."""

    def __init__(
        self,
        client: Any = None,
        model_manager: Any = None,
        timeout: float = 10.0,
        fallback_reason: str = "timeout",
        cognitive_state: Any = None,
    ):
        self.client = client
        self.model_manager = model_manager
        self.timeout = timeout
        self.fallback_reason = fallback_reason
        self.cognitive_state = cognitive_state

    def _build_system_prompt(self, base_prompt: str = "") -> str:
        tone_context = self.cognitive_state.get_tone_context() if self.cognitive_state else ""
        system_prompt = f"""{tone_context}

You are FRIDAY, a local-first JARVIS-style AI assistant. Respond helpfully, accurately, and concisely.
{base_prompt}""".strip()
        return system_prompt

    async def generate(self, prompt: str, max_tokens: int = 500) -> Any:
        full_prompt = self._build_system_prompt(prompt) if self.cognitive_state else prompt
        try:
            response = await asyncio.wait_for(
                self.client.generate(full_prompt, max_tokens=max_tokens),
                timeout=self.timeout  # 10 seconds
            )
        except asyncio.TimeoutError:
            logger.warning("llm_timeout: model took >10s, escalating to 7B")
            if self.model_manager and getattr(self.model_manager, "current_model", None) != "7b":
                await self.model_manager.switch_model("7b", self.fallback_reason)
            # Retry with 7B
            response = await self.client.generate(full_prompt, max_tokens=max_tokens)
        return response
