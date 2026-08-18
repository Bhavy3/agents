from __future__ import annotations

from core.llm.local_llm_client import (
    LocalLLMClient,
    LlmResponse,
    LlmRequestMetrics,
    parse_llm_response,
)


class OllamaClient(LocalLLMClient):
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        super().__init__(
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            provider="ollama",
        )
