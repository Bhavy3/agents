"""Step 7: Live tone test on real hardware.
Starts model via ModelManager, executes 6 queries sequentially,
evaluates tone detection and phrasing.
"""
import asyncio
import httpx
import logging

from core.cognition.tone_detector import detect_tone
from core.cognition.cognitive_state import CognitiveStateEngine
from core.llm.model_manager import ModelManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("live_tone_test")

QUERIES = [
    ("Can you build me a todo app", "confident"),
    ("Not sure if Python is the right choice here", "cautious"),
    ("Deep dive into how transformers work", "curious"),
    ("I'm frustrated, the code keeps crashing", "warm"),
    ("Tell me a joke", "curious"),
    ("Do this exactly as I say", "confident"),
]


async def run_live_test():
    mm = ModelManager()
    logger.info("Starting llama-server via ModelManager on real hardware...")
    await mm.load_model("3b")
    await asyncio.sleep(3)

    engine = CognitiveStateEngine(None)
    history = []
    results = []

    url = "http://127.0.0.1:8080/v1/chat/completions"

    async with httpx.AsyncClient(timeout=30.0) as client:
        for query, expected_tone in QUERIES:
            # 1. Infer tone (single-turn per requirement)
            detected_tone = detect_tone(query)
            await engine.update_tone(query)
            tone_ctx = engine.get_tone_context()

            # 2. Query LLM with tone modulation prefix
            system_prompt = (
                f"{tone_ctx}\n\n"
                "You are FRIDAY, a local-first JARVIS-style AI assistant. "
                "Keep responses concise (1 to 2 sentences max)."
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ]

            resp = await client.post(
                url,
                json={"messages": messages, "max_tokens": 80, "temperature": 0.7},
            )
            data = resp.json()
            response_text = data["choices"][0]["message"]["content"].strip()
            sample_100 = response_text.replace("\n", " ")[:100]

            tone_match = "YES" if detected_tone == expected_tone else "NO"
            results.append({
                "query": query,
                "expected": expected_tone,
                "detected": detected_tone,
                "sample": sample_100,
                "match": tone_match,
            })
            history.append(query)
            history.append(response_text)

    # Cleanup server
    if mm.process:
        mm.process.terminate()
        try:
            mm.process.wait(timeout=5)
        except Exception:
            mm.process.kill()

    print("\n=== STEP 7: LIVE TONE TEST RESULTS ===")
    for idx, r in enumerate(results, 1):
        print(f"\n{idx}. Query: \"{r['query']}\"")
        print(f"   Expected tone: {r['expected']}")
        print(f"   Detected tone: {r['detected']}")
        print(f"   Phrasing sample: \"{r['sample']}\"")
        print(f"   Tone match: {r['match']}")


if __name__ == "__main__":
    asyncio.run(run_live_test())
