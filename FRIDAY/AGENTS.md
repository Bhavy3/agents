Good news: the conversation itself worked correctly - real audio played multiple
times, and the semantic self-feedback filter caught and correctly dropped one echo
("Understood.") instead of looping. Both defense layers are functioning.

One remaining issue: a RuntimeError during Pa_Terminate happens on shutdown (Ctrl+C)
- this is the continuously-open output stream not being cleanly closed before the
asyncio event loop tears down. This doesn't affect the live conversation, only
happens on exit.

Fix: ensure TtsWorker's output stream is explicitly stopped and closed in a proper
shutdown/cleanup method BEFORE the event loop closes, rather than relying on
sounddevice's atexit handler to clean it up after the loop is already gone. Add
this to whatever shutdown sequence FRIDAY already has for other workers.

Also: reduce/remove the "TTS DEBUG: received chunk" WARNING-level spam - we
temporarily elevated it for visibility, but now that we've confirmed the fix works,
downgrade it back to DEBUG or remove it, the terminal is very noisy again.

Verify: run main.py, have a real conversation, and this time exit cleanly (type
'exit' if that's supported, or confirm Ctrl+C no longer throws that traceback).
