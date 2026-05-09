# FRIDAY Agent Instructions

- Prioritize stability, async architecture, and modularity over feature speed.
- Keep `main.py` as a runtime entrypoint only.
- Keep `core/app.py` responsible for lifecycle orchestration.
- Route all module communication through the event bus.
- Keep execution dry-run until real execution is explicitly approved.
- Do not let LLM output directly execute commands.
- Keep modules independently testable.
