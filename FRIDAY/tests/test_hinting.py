import asyncio
import pytest
from core.orchestrator.intent_hinting import PassiveHintEngine, ContextDependency

@pytest.mark.asyncio
async def test_hinting():
    engine = PassiveHintEngine()
    
    # Test 1: Technical task
    hint1 = await engine.generate_hint("fix the bug in my code", None, [])
    print(f"Test 1 (Technical): {hint1.intent_hint} (Conf: {hint1.confidence})")
    assert hint1.intent_hint == "technical_task"
    
    # Test 2: Continuation
    hint2 = await engine.generate_hint("continue with the next step", "workflow", [])
    print(f"Test 2 (Continuation): {hint2.intent_hint} (Dependency: {hint2.context_dependency})")
    assert hint2.intent_hint == "continuation_request"
    assert hint2.context_dependency == ContextDependency.ACTIVE_ATTENTION
    
    # Test 3: Pivot
    hint3 = await engine.generate_hint("actually forget that, search for something else", None, [])
    print(f"Test 3 (Pivot): {hint3.intent_hint}")
    assert hint3.intent_hint == "topic_pivot"
 
    # Test 4: Workflow context
    hint4 = await engine.generate_hint("what is the status?", "workflow", [])
    print(f"Test 4 (Workflow Context): {hint4.intent_hint}")
    assert hint4.intent_hint == "workflow_clarification"

    print("ALL HINTING TESTS PASSED")

if __name__ == "__main__":
    asyncio.run(test_hinting())
