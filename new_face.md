PS C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents> python main.py --burn-in --duration-seconds 500
C:\Users\IQ\AppData\Local\Programs\Python\Python312\python.exe: can't open file 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\main.py': [Errno 2] No such file or directory
PS C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents>





PS C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents> python main.py --burn-in --duration-seconds 500
--duration-seconds 500
C:\Users\IQ\AppData\Local\Programs\Python\Python312\python.exe: can't open file 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\main.py': [Errno 2] No such file or directory
PS C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents> cd FRIDAY
PS C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY> python main.py --burn-in --duration-seconds 500
08:48:37 | WARN | friday.app | ollama_unavailable_at_startup [model=qwen2.5-3b-instruct-q5_k_m]
08:48:37 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:37 | WARN | friday.audio.tts | tts_no_model_or_library_degraded_mode
08:48:37 | WARN | friday.workers.ocr_worker | tesseract_not_found_vision_degraded
08:48:37 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:37 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:37 | ERRO | friday.workers.validation_crash_worker | Worker validation_crash_worker failed during run: simulated validation worker crash
08:48:38 | ERRO | friday.workers.supervisor | worker_failed [worker=validation_crash_worker state=failed restart_count=0 error=simulated validation worker crash]
08:48:38 | WARN | friday.workers.supervisor | worker_restart_scheduled [worker=validation_crash_worker delay_seconds=1.0 restart_count=1 state=restarting]
08:48:38 | WARN | friday.recovery.manager | worker_failure_recorded [worker=validation_crash_worker failure_count=1]
08:48:38 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:38 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:39 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:43 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:43 | ERRO | friday.workers.validation_crash_worker | Worker validation_crash_worker failed during run: simulated validation worker crash
08:48:43 | ERRO | friday.workers.supervisor | worker_failed [worker=validation_crash_worker state=failed restart_count=1 error=simulated validation worker crash]
08:48:43 | WARN | friday.workers.supervisor | worker_restart_scheduled [worker=validation_crash_worker delay_seconds=2.0 restart_count=2 state=restarting]
08:48:43 | WARN | friday.recovery.manager | worker_failure_recorded [worker=validation_crash_worker failure_count=2]
08:48:43 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:43 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:44 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:44 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:44 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:47 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:47 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:48:48 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:49 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:49 | ERRO | friday.workers.validation_crash_worker | Worker validation_crash_worker failed during run: simulated validation worker crash
08:48:49 | ERRO | friday.workers.supervisor | worker_failed [worker=validation_crash_worker state=failed restart_count=2 error=simulated validation worker crash]
08:48:49 | WARN | friday.workers.supervisor | worker_restart_scheduled [worker=validation_crash_worker delay_seconds=4.0 restart_count=3 state=restarting]
08:48:49 | WARN | friday.recovery.manager | worker_failure_recorded [worker=validation_crash_worker failure_count=3]
08:48:49 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:49 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:49 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:50 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:52 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:52 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:48:52 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]        
08:48:52 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]        
08:48:52 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]        
08:48:52 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]        
08:48:52 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]        
08:48:54 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:56 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:56 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:48:56 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:48:56 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]        
08:48:56 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:56 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]
08:48:56 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:48:56 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]        
08:48:57 | ERRO | friday.workers.validation_crash_worker | Worker validation_crash_worker failed during run: simulated validation worker crash
08:48:58 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:59 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:48:59 | ERRO | friday.workers.supervisor | worker_failed [worker=validation_crash_worker state=failed restart_count=3 error=simulated validation worker crash]
08:48:59 | WARN | friday.workers.supervisor | worker_restart_scheduled [worker=validation_crash_worker delay_seconds=8.0 restart_count=4 state=restarting]
08:48:59 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:48:59 | WARN | friday.recovery.manager | worker_failure_recorded [worker=validation_crash_worker failure_count=4]
08:48:59 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:48:59 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:48:59 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]        
08:48:59 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]        
08:48:59 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:49:00 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:02 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:03 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:03 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]
08:49:03 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]
08:49:03 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]        
08:49:03 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]        
08:49:03 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]
08:49:03 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]        
08:49:03 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:49:04 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:04 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:04 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:04 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:04 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:04 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:04 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:04 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:05 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:07 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:07 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:49:07 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]
08:49:07 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]        
08:49:07 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]        
08:49:07 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]        
08:49:07 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]        
08:49:07 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]        
08:49:07 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:07 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:07 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:07 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:07 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:07 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:07 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:07 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:08 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:08 | ERRO | friday.workers.validation_crash_worker | Worker validation_crash_worker failed during run: simulated validation worker crash
08:49:08 | ERRO | friday.workers.supervisor | worker_failed [worker=validation_crash_worker state=failed restart_count=4 error=simulated validation worker crash]
08:49:08 | WARN | friday.workers.supervisor | worker_restart_scheduled [worker=validation_crash_worker delay_seconds=16.0 restart_count=5 state=restarting]  
08:49:08 | WARN | friday.recovery.manager | worker_failure_recorded [worker=validation_crash_worker failure_count=5]
08:49:09 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 25, in main
    report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\orchestrator\conversation.py", line 228, in _route_and_execute
    intent = await self.intent_router.route(
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\intent_router.py", line 46, in route
    return await self.llm_fallback.route(text, correlation_id=correlation_id, personality_instructions=personality_instructions)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\llm_fallback.py", line 44, in route
    raw_response, metrics = await self.ollama.generate(self._build_prompt(text, personality_instructions))
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 209, in generate
    if not await self._ensure_available(attempt):
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 388, in _ensure_available
    if await self.health_check():
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 176, in health_check
    self.logger.info(
Message: 'llm_health_check'
Arguments: ()
08:49:11 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]        
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 25, in main
    report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\orchestrator\conversation.py", line 228, in _route_and_execute
    intent = await self.intent_router.route(
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\intent_router.py", line 46, in route
    return await self.llm_fallback.route(text, correlation_id=correlation_id, personality_instructions=personality_instructions)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\llm_fallback.py", line 44, in route
    raw_response, metrics = await self.ollama.generate(self._build_prompt(text, personality_instructions))
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 209, in generate
    if not await self._ensure_available(attempt):
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 390, in _ensure_available
    self.logger.warning(
Message: 'llm_unavailable_before_generate'
Arguments: ()
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 25, in main
    report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\orchestrator\conversation.py", line 228, in _route_and_execute
    intent = await self.intent_router.route(
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\intent_router.py", line 46, in route
    return await self.llm_fallback.route(text, correlation_id=correlation_id, personality_instructions=personality_instructions)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\llm_fallback.py", line 44, in route
    raw_response, metrics = await self.ollama.generate(self._build_prompt(text, personality_instructions))
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 209, in generate
    if not await self._ensure_available(attempt):
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 388, in _ensure_available
    if await self.health_check():
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 176, in health_check
    self.logger.info(
Message: 'llm_health_check'
Arguments: ()
08:49:11 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]        
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 25, in main
    report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\orchestrator\conversation.py", line 228, in _route_and_execute
    intent = await self.intent_router.route(
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\intent_router.py", line 46, in route
    return await self.llm_fallback.route(text, correlation_id=correlation_id, personality_instructions=personality_instructions)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\llm_fallback.py", line 44, in route
    raw_response, metrics = await self.ollama.generate(self._build_prompt(text, personality_instructions))
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 209, in generate
    if not await self._ensure_available(attempt):
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 390, in _ensure_available
    self.logger.warning(
Message: 'llm_unavailable_before_generate'
Arguments: ()
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 25, in main
    report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\orchestrator\conversation.py", line 228, in _route_and_execute
    intent = await self.intent_router.route(
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\intent_router.py", line 46, in route
    return await self.llm_fallback.route(text, correlation_id=correlation_id, personality_instructions=personality_instructions)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\llm_fallback.py", line 44, in route
    raw_response, metrics = await self.ollama.generate(self._build_prompt(text, personality_instructions))
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 209, in generate
    if not await self._ensure_available(attempt):
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 388, in _ensure_available
    if await self.health_check():
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 176, in health_check
    self.logger.info(
Message: 'llm_health_check'
Arguments: ()
08:49:11 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]        
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 25, in main
    report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\orchestrator\conversation.py", line 228, in _route_and_execute
    intent = await self.intent_router.route(
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\intent_router.py", line 46, in route
    return await self.llm_fallback.route(text, correlation_id=correlation_id, personality_instructions=personality_instructions)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\llm_fallback.py", line 44, in route
    raw_response, metrics = await self.ollama.generate(self._build_prompt(text, personality_instructions))
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 209, in generate
    if not await self._ensure_available(attempt):
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 390, in _ensure_available
    self.logger.warning(
Message: 'llm_unavailable_before_generate'
Arguments: ()
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 25, in main
    report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\orchestrator\conversation.py", line 228, in _route_and_execute
    intent = await self.intent_router.route(
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\intent_router.py", line 46, in route
    return await self.llm_fallback.route(text, correlation_id=correlation_id, personality_instructions=personality_instructions)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\llm_fallback.py", line 44, in route
    raw_response, metrics = await self.ollama.generate(self._build_prompt(text, personality_instructions))
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 209, in generate
    if not await self._ensure_available(attempt):
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 388, in _ensure_available
    if await self.health_check():
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 176, in health_check
    self.logger.info(
Message: 'llm_health_check'
Arguments: ()
08:49:11 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 25, in main
    report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\orchestrator\conversation.py", line 228, in _route_and_execute
    intent = await self.intent_router.route(
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\intent_router.py", line 46, in route
    return await self.llm_fallback.route(text, correlation_id=correlation_id, personality_instructions=personality_instructions)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\llm_fallback.py", line 44, in route
    raw_response, metrics = await self.ollama.generate(self._build_prompt(text, personality_instructions))
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 209, in generate
    if not await self._ensure_available(attempt):
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 390, in _ensure_available
    self.logger.warning(
Message: 'llm_unavailable_before_generate'
Arguments: ()
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 25, in main
    report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\workers\base_worker.py", line 33, in run
    await self.work()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\audio\transport.py", line 128, in work
    self.heartbeat(f"audio_streaming [buffer={len(self._buffer)}/{self.max_buffer_chunks} chunks={self._total_chunks}]")
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\workers\base_worker.py", line 57, in heartbeat
    self.health.mark_alive(task)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\workers\health.py", line 49, in mark_alive
    self.transition(WorkerState.RUNNING, task, True)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\workers\health.py", line 36, in transition
    get_logger("workers.state").info(
Message: 'worker_state_transition'
Arguments: ()
08:49:11 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 25, in main
    report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\validation\runtime_validator.py", line 136, in _simulate_malformed_events
    await self.app.event_bus.publish_raw_for_validation("malformed-event")
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\events\bus.py", line 88, in publish_raw_for_validation
    await self.publish(raw_event)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\events\bus.py", line 71, in publish
    if not self._validate_event_boundary(event):
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\events\bus.py", line 240, in _validate_event_boundary
    self._drop_malformed_event(
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\events\bus.py", line 294, in _drop_malformed_event
    self._logger.error(
Message: 'malformed_event_dropped'
Arguments: ()
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 25, in main
    report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\orchestrator\conversation.py", line 228, in _route_and_execute
    intent = await self.intent_router.route(
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\intent_router.py", line 46, in route
    return await self.llm_fallback.route(text, correlation_id=correlation_id, personality_instructions=personality_instructions)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\llm_fallback.py", line 44, in route
    raw_response, metrics = await self.ollama.generate(self._build_prompt(text, personality_instructions))
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 209, in generate
    if not await self._ensure_available(attempt):
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 388, in _ensure_available
    if await self.health_check():
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 176, in health_check
    self.logger.info(
Message: 'llm_health_check'
Arguments: ()
08:49:11 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]        
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 25, in main
    report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\orchestrator\conversation.py", line 228, in _route_and_execute
    intent = await self.intent_router.route(
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\intent_router.py", line 46, in route
    return await self.llm_fallback.route(text, correlation_id=correlation_id, personality_instructions=personality_instructions)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\llm_fallback.py", line 44, in route
    raw_response, metrics = await self.ollama.generate(self._build_prompt(text, personality_instructions))
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 209, in generate
    if not await self._ensure_available(attempt):
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 390, in _ensure_available
    self.logger.warning(
Message: 'llm_unavailable_before_generate'
Arguments: ()
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 25, in main
    report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\orchestrator\conversation.py", line 228, in _route_and_execute
    intent = await self.intent_router.route(
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\intent_router.py", line 46, in route
    return await self.llm_fallback.route(text, correlation_id=correlation_id, personality_instructions=personality_instructions)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\llm_fallback.py", line 44, in route
    raw_response, metrics = await self.ollama.generate(self._build_prompt(text, personality_instructions))
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 209, in generate
    if not await self._ensure_available(attempt):
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 388, in _ensure_available
    if await self.health_check():
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 176, in health_check
    self.logger.info(
Message: 'llm_health_check'
Arguments: ()
08:49:11 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]        
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 25, in main
    report = asyncio.run(FridayApp().run_validation(args.duration_seconds))
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\orchestrator\conversation.py", line 228, in _route_and_execute
    intent = await self.intent_router.route(
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\intent_router.py", line 46, in route
    return await self.llm_fallback.route(text, correlation_id=correlation_id, personality_instructions=personality_instructions)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\router\llm_fallback.py", line 44, in route
    raw_response, metrics = await self.ollama.generate(self._build_prompt(text, personality_instructions))
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 209, in generate
    if not await self._ensure_available(attempt):
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\llm\local_llm_client.py", line 390, in _ensure_available
    self.logger.warning(
Message: 'llm_unavailable_before_generate'
Arguments: ()
08:49:11 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]
08:49:12 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:13 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:13 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:13 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:13 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:13 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:14 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:14 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:49:14 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:15 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:15 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:49:15 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:15 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:17 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]
08:49:17 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:17 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:49:17 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:49:18 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:19 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
08:49:19 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:49:19 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]        
08:49:19 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:20 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:20 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:49:21 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:22 | ERRO | friday.events.bus | malformed_event_dropped [reason=invalid_event_object event_class=str]
08:49:22 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]
08:49:22 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]        
PS C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY> Stop-Process -Name "python" -Force
Stop-Process : Cannot find a process with the name "python". Verify the process name and call the cmdlet again.
At line:1 char:1
+ Stop-Process -Name "python" -Force
+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : ObjectNotFound: (python:String) [Stop-Process], ProcessCommandException
    + FullyQualifiedErrorId : NoProcessFoundForGivenName,Microsoft.PowerShell.Commands.StopProcessCommand

PS C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY> python main.py
08:51:16 | WARN | friday.app | ollama_unavailable_at_startup [model=qwen2.5-3b-instruct-q5_k_m]
FRIDAY online. Type 'help' or 'exit'.
You > 08:51:16 | WARN | friday.audio.tts | tts_no_model_or_library_degraded_mode
08:51:16 | WARN | friday.workers.ocr_worker | tesseract_not_found_vision_degraded
hi
You > 08:51:37 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:51:43 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]
08:51:43 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
FRIDAY > hi
hello bro how are you 
You > 08:52:09 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=1 base_url=http://localhost:11434]
08:52:14 | WARN | friday.llm.local | llm_unavailable_before_generate [provider=ollama model=qwen2.5-3b-instruct-q5_k_m attempt=2 base_url=http://localhost:11434]
08:52:14 | ERRO | friday.llm.local | llm_generate_failed [provider=ollama model=qwen2.5-3b-instruct-q5_k_m retries=2 error=llm_unavailable]
FRIDAY > hello bro how are you
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 28, in main
    asyncio.run(run_app())
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\workers\base_worker.py", line 33, in run
    await self.work()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\audio\transport.py", line 128, in work
    self.heartbeat(f"audio_streaming [buffer={len(self._buffer)}/{self.max_buffer_chunks} chunks={self._total_chunks}]")
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\workers\base_worker.py", line 57, in heartbeat
    self.health.mark_alive(task)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\workers\health.py", line 49, in mark_alive
    self.transition(WorkerState.RUNNING, task, True)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\workers\health.py", line 36, in transition
    get_logger("workers.state").info(
Message: 'worker_state_transition'
Arguments: ()
--- Logging error ---
Traceback (most recent call last):
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 74, in emit
    self.doRollover()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 179, in doRollover
    self.rotate(self.baseFilename, dfn)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\logging\handlers.py", line 115, in rotate
    os.rename(source, dest)
PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log' -> 'C:\\Users\\IQ\\OneDrive\\Music\\Documents\\padas 1\\agents\\FRIDAY\\data\\logs\\friday.log.1'
Call stack:
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 34, in <module>
    main()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\main.py", line 28, in main
    asyncio.run(run_app())
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 678, in run_until_complete
    self.run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\windows_events.py", line 322, in run_forever
    super().run_forever()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 645, in run_forever
    self._run_once()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\base_events.py", line 1999, in _run_once
    handle._run()
  File "C:\Users\IQ\AppData\Local\Programs\Python\Python312\Lib\asyncio\events.py", line 88, in _run
    self._context.run(self._callback, *self._args)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\vision\ocr_worker.py", line 23, in run
    await super().run()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\workers\base_worker.py", line 33, in run
    await self.work()
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\vision\ocr_worker.py", line 40, in work
    self.heartbeat(f"ocr_active [available={self._tesseract_available}]")
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\workers\base_worker.py", line 57, in heartbeat
    self.health.mark_alive(task)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\workers\health.py", line 49, in mark_alive
    self.transition(WorkerState.RUNNING, task, True)
  File "C:\Users\IQ\OneDrive\Music\Documents\padas 1\agents\FRIDAY\core\workers\health.py", line 36, in transition
    get_logger("workers.state").info(
Message: 'worker_state_transition'
Arguments: ()
