# FRIDAY new-machine setup plan (Windows)

## Scope and findings

This plan is based on the checked-in `agents/agents/FRIDAY` project. It assumes the new machine is Windows, as the runtime uses Windows desktop automation and the included launcher is a `.bat` file. Confirm the Windows version, CPU/GPU, RAM, available disk, and microphone/speaker before choosing an LLM model or enabling GPU acceleration.

The project already contains its Silero VAD model and two Piper TTS voice pairs under `data/models`; together they are about 124 MB. The LLM executable and GGUF model are not included. `start_llm.bat` points to `D:\AI\...`, so it must be replaced or configured for the new machine. The runtime defaults to the llama.cpp HTTP API at `127.0.0.1:8080`, model label `qwen2.5-3b-instruct-q5_k_m`, and provider `llamacpp`.

`requirements.txt` is incomplete for the application: it lists Pydantic, Rich, pytest, and colorlog, while runtime imports also need packages for HTTP, audio, vision, OCR, desktop control, and the Pipecat pipeline. Build a pinned, verified runtime dependency file from a clean environment before treating setup as reproducible. Python 3.12 is a reasonable target consistent with the README and prior runtime logs. `audioop` is used by the audio worker; Python 3.13 removed this standard-library module, so stay on 3.12 unless compatibility is fixed.

## Dependency inventory

### Machine-level prerequisites

- Windows 10/11, current updates, and current GPU driver if using NVIDIA acceleration.
- Python 3.12 x64 and `py` launcher; Git if cloning/pulling the project.
- Working microphone and output device. Select the right devices after installation.
- Tesseract OCR executable for screen OCR. `pytesseract` is only its Python wrapper; it does not install Tesseract itself.
- llama.cpp `llama-server.exe` build, plus a compatible GGUF chat/instruct model. Choose a CPU build or a GPU-enabled build that matches the actual GPU and driver. Begin with CPU or modest GPU offload; do not copy `-ngl 999` blindly.

### Python runtime packages

Directly visible runtime imports imply at least:

- `httpx`, `numpy`, `pydantic`, `rich`, `colorlog`
- `sounddevice` and Pipecat with local audio, Whisper STT, and Silero VAD support
- `faster-whisper` (Pipecat's Whisper service downloads its model on first run unless cached)
- `piper-tts` and `onnxruntime` for local speech output and VAD/TTS model execution
- `mss`, `Pillow`, `pytesseract`, `pyautogui` for screen capture, OCR, and desktop input
- `aec-audio-processing` is optional: the code treats it as unavailable if not installed.
- `pyaudio` is optional and used only to match a named output device; it may need a matching Windows wheel/build. Device selection can be configured by index without it.

Pin exact versions only after resolving and running the application in a fresh Python 3.12 environment. Audio packages can have platform-specific wheels and should be installed/verified on the target machine. `pytest` is for development verification, not required to run the app. `asyncio` is in Python's standard library and must not be installed from PyPI.

### Model and data files

Present in the project:

- `data/models/vad/silero_vad.onnx`
- `data/models/tts/en_US-hfc_female-medium.onnx` and its `.json`
- `data/models/tts/en_US-lessac-medium.onnx` and its `.json`

Fetched/cached outside the checked-in files:

- The `tiny` Whisper model used by the active Pipecat worker. First initialization needs internet access or a pre-populated model cache.
- A GGUF LLM model for llama.cpp. It is a separate, potentially multi-GB download. Record its exact source, filename, size, and checksum in the machine setup notes. Match the GGUF chat template to the model and validate its license for the intended use.

## Recommended installation sequence

1. **Record target hardware.** Note Windows edition/build, CPU, RAM, GPU model/VRAM and driver, free disk, microphone and speakers. Keep the model choice open until these are known. Keep at least the model's file size plus working space free; allow extra disk for Python wheels, Whisper cache, and logs.
2. **Place the project in a stable local path.** For example `C:\AI\FRIDAY`. Avoid synced/managed folders while validating audio, native libraries, and logs. Preserve project data/model files when updating code.
3. **Install machine prerequisites.** Install Python 3.12 x64 and Git. Install/update NVIDIA drivers only if the machine has an NVIDIA GPU and the chosen llama.cpp build uses it. Install Tesseract OCR and note its executable path. Connect and test microphone and speakers in Windows.
4. **Create a clean virtual environment.** In PowerShell from the FRIDAY project directory:

   ```powershell
   py -3.12 --version
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   ```

   If PowerShell blocks activation, use `\.venv\Scripts\python.exe -m pip ...` directly; changing machine-wide execution policy is unnecessary.
5. **Resolve Python dependencies.** Install runtime packages from a newly audited/pinned runtime requirements file. Keep test tools in a development requirements file. Verify imports for the actual audio stack (`pipecat`, `sounddevice`, `faster_whisper`, `piper`, `onnxruntime`) and the UI/vision stack (`mss`, `PIL`, `pytesseract`, `pyautogui`). Add optional `pyaudio` only if named-device lookup is needed. Do not regard the current short `requirements.txt` as a complete install specification.
6. **Configure and verify Tesseract.** Ensure `tesseract --version` works in a fresh PowerShell session. If it is not on PATH, set the supported `pytesseract` executable path in project configuration/code as appropriate and document it.
7. **Install llama.cpp.** Obtain a trusted Windows release/build for the target CPU/GPU from the official project distribution. Extract it to a stable path such as `C:\AI\llama.cpp`; verify `llama-server.exe --version` and keep track of whether the build has GPU support. Avoid copying the old machine's absolute `D:\AI` paths.
8. **Choose and obtain one GGUF model.** Start with a small 3B-class instruct model only if its license, quality, and hardware fit are acceptable. Store it outside the code checkout, for example `C:\AI\models\...gguf`; verify its checksum. A quantized 3B model is still several GB and GPU offload needs VRAM in addition to model storage. Do not select a model based only on the old launcher filename.
9. **Replace machine-specific startup configuration.** Configure the launcher with actual executable/model paths and a conservative context length. Bind the server to `127.0.0.1` and the configured port `8080`; do not expose it on the network. Use a moderate `-ngl` value or CPU-only initially. Set `FRIDAY_LLM_PROVIDER=llamacpp`, `FRIDAY_LLM_BASE_URL=http://127.0.0.1:8080`, and `FRIDAY_LLM_MODEL` as needed. Consider changing the hard-coded defaults or providing a documented `.env` loader; settings currently read environment variables directly.
10. **Smoke-test llama.cpp before starting FRIDAY.** Launch the server and confirm its health/models endpoint responds locally. Send a simple request to `http://127.0.0.1:8080/v1/chat/completions`; verify that the selected model returns a sensible response and note first-token latency and memory/VRAM use.
11. **Verify the audio path.** Run FRIDAY with the LLM server active. Confirm Pipecat opens the intended microphone/output, Silero VAD loads, Whisper `tiny` downloads/loads, and speech input produces a transcript. Confirm the selected Piper voice and config exist and speech output is audible. If needed, set `FRIDAY_AUDIO_INPUT_DEVICE`, `FRIDAY_AUDIO_OUTPUT_DEVICE`, and/or `FRIDAY_TTS_MODEL_PATH` / `FRIDAY_TTS_CONFIG_PATH` to valid target-machine values.
12. **Verify vision and desktop dependencies.** Check screen capture and OCR with Tesseract. Check desktop-control libraries in a safe development session. The runtime constant `DRY_RUN_MODE=True` does not make every desktop helper inert: `DesktopTools.launch_app`, keyboard, and mouse methods call real OS APIs. Keep use limited to a trusted local session and verify command/confirmation behavior before enabling real automation.
13. **Run project verification.** From the project directory, run the documented test suite in the development environment, then launch `python main.py` and exercise `help`, `status`, text chat, speech input/output, and orderly shutdown. Fix code/config issues discovered before treating the machine as ready.
14. **Make startup repeatable.** Add a launcher that activates the project environment and starts llama.cpp with the configured model, then starts FRIDAY only after the LLM endpoint is ready. Keep paths configurable, log model/build versions, and add a short recovery note for model-cache or audio-device failures.

## Readiness checklist

- [ ] Target-machine hardware and model choice recorded.
- [ ] Python 3.12 x64 virtual environment installs cleanly from a complete pinned runtime requirements file.
- [ ] Tesseract executable and audio devices are available.
- [ ] llama.cpp build runs on the target machine and uses only intended CPU/GPU resources.
- [ ] GGUF source, license, size, and checksum recorded; local chat-completions request succeeds.
- [ ] Whisper, Silero VAD, and Piper load; speech is transcribed and spoken.
- [ ] OCR/screen capture and expected desktop interactions work.
- [ ] Tests and normal app startup/shutdown complete successfully.
- [ ] Startup script contains no stale machine-specific paths and server listens on loopback only.

## Risks / unresolved details

- The target computer specifications were not provided, so GPU backend, LLM size/quantization, context length, and offload cannot yet be sized responsibly.
- The checked-in `requirements.txt` is not sufficient for runtime imports, and no lockfile is present. Create and validate a complete lock/requirements set before doing a clean-machine install.
- Pipecat's Whisper model and the GGUF model require external downloads; offline setup requires pre-staging both model caches/files.
- The app currently instantiates the Pipecat audio worker unconditionally, while parts of the legacy `sounddevice`/faster-whisper path are optional/degraded. Treat the Pipecat dependencies as required for the intended voice app.
- `audioop` usage makes Python 3.13 a compatibility risk.
- The included batch file uses stale absolute paths and `-ngl 999`; it is not portable or a safe hardware default.
