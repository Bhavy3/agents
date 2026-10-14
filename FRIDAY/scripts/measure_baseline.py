"""Measure FRIDAY baseline response time (user prompt to first token)."""
import asyncio
import time
import httpx

QUERIES = [
    "What's the weather?",
    "What time is it?",
    "Tell me a joke",
    "How are you?",
    "Thanks for helping",
]


async def measure():
    url = "http://127.0.0.1:8080/v1/chat/completions"
    ttft_times = []
    total_times = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Warmup query
        await client.post(url, json={"messages": [{"role": "user", "content": "hi"}], "max_tokens": 10})

        for q in QUERIES:
            t0 = time.perf_counter()
            first_token_time = None
            response_chunks = []

            async with client.stream(
                "POST",
                url,
                json={"messages": [{"role": "user", "content": q}], "max_tokens": 60, "temperature": 0.7, "stream": True},
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line.strip() != "data: [DONE]":
                        if first_token_time is None:
                            first_token_time = time.perf_counter() - t0
                        response_chunks.append(line)

            elapsed_total = time.perf_counter() - t0
            ttft = first_token_time or elapsed_total
            ttft_times.append(ttft)
            total_times.append(elapsed_total)
            print(f"Query: '{q}' -> TTFT (First Token): {ttft:.2f}s | Total: {elapsed_total:.2f}s")

    mean_ttft = sum(ttft_times) / len(ttft_times)
    mean_total = sum(total_times) / len(total_times)
    print("\n--- BASELINE RESPONSE TIME RESULTS ---")
    for q, t in zip(QUERIES, ttft_times):
        print(f"  {q}: {t:.2f}s")
    print(f"\nMean TTFT (First Token): {mean_ttft:.2f}s (target: 0.88s ± 0.3s)")
    print(f"Mean Total Time: {mean_total:.2f}s")


if __name__ == "__main__":
    asyncio.run(measure())
