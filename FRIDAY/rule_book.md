We are building FRIDAY, a local-first resilient AI operating system for Windows. Current stage: Phase 1.8 operational maturity. The runtime core already exists and passes burn-in tests with async event bus, worker supervision, restart recovery, quarantine handling, backpressure protection, structured logging, and dry-run execution. We are NOT building new AI features yet. We are improving stability, observability, operator control, and graceful lifecycle management only.

Rules:

* Minimal-change policy always.
* Fix root causes instead of adding architecture.
* Do NOT create new managers, frameworks, wrappers, orchestration systems, or abstraction layers unless explicitly requested.
* Prefer modifying existing files over creating new ones.
* Keep fixes localized and surgical.
* Avoid line-count explosion. A 20-line correct fix is preferred over a 300-line redesign.
* Preserve current architecture and folder structure.
* Do NOT implement voice, GUI, browser automation, desktop control, networking, vision, or God Mode.
* Every feature must survive burn-in and stress tests before moving forward.
* Use explicit lifecycle/state transitions.
* Maintain clean async behavior and graceful recovery.
* Generate only the exact amount of code necessary for the requested task.
* If a simpler solution exists, choose the simpler solution.
* Prioritize operational correctness, readability, and maintainability over “smart” architecture.

Current focus for Phase 1.8:

* structured logging cleanup
* runtime dashboard
* graceful shutdown
* operator CLI commands
* centralized config hardening
* metrics snapshots
* burn-in automation

Do not redesign the system. Extend it carefully.
