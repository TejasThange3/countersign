# Lane: voice

TASK: Build the real-time voice agent and a text mode for it.
- The voice agent is a Pipecat pipeline served by FastAPI, with:
  - Silero VAD + turn detection
  - ElevenLabs Scribe STT
  - Gemini Flash with tool calling
  - ElevenLabs Flash TTS
  - barge-in
- Text mode is the same agent with STT and TTS skipped.
- Tools come only from a `ToolGateway`, defined in
  apps/agent/src/countersign_agent/contracts.py (owned by main).
- The bridge lane builds the real gateway in parallel, so you build and test against your own
  fake gateway.

CONTEXT:
- AGENTS.md
- scope sections:
  - 2 ("Own pipeline", "Two run modes")
  - 3 (architecture)
  - 4 ("Voice-specific behaviour for holds")
  - 6 (agent server stack)
- contracts.py

FILES YOU OWN:
- apps/agent/src/countersign_agent/voice/**: the pipeline, prompts, hold UX and transports.
- apps/agent/src/countersign_agent/app.py and the config for it. app.py is the FastAPI app:
  - SmallWebRTC offer endpoint
  - WebSocket endpoint for the simulator
  - text-mode endpoint
  - /health
- apps/agent/tests/voice/** and apps/agent/tests/test_app.py
- apps/agent/pyproject.toml and apps/agent/uv.lock, granted to this lane. Keep the dependencies
  main added: armoriq-sdk==0.6.10, fastmcp, pydantic-settings, httpx and pydantic.
- notes-drafts/voice.md

DO NOT TOUCH: contracts.py, bridge/**, cli_text.py.

DESIGN REQUIREMENTS:
1. Convert each `ToolSpec` into a Pipecat function definition, with a handler that calls
   `gateway.call(...)`. The system prompt is identical with and without ArmorIQ.
2. Holds. This is the voice UX the judges will see.
   - On PENDING, the agent immediately says something like "That needs a manager's approval, one
     moment".
   - It plays short filler while `gateway.wait()` runs as a background task, never blocking the
     pipeline.
   - Then it continues, or explains the refusal. A timeout counts as a refusal.
   - If the caller speaks during the wait, acknowledge them without starting a new tool call for
     the same request.
   - If the caller hangs up, cancel the wait.
3. Text mode:
   - Transcripts go in and text comes out, through the same LLM and gateway path, with no STT or
     TTS.
   - Expose it so the evals lane can drive whole conversations without spending credits.
4. Metrics: set `enable_metrics=True` and record, for each turn, STT final, LLM TTFT and TTS
   TTFB.
5. Gateway wiring:
   - app.py loads its `GatewayFactory` from an import path in config:
     `GATEWAY_FACTORY=countersign_agent.bridge:factory` once the bridge merges, and your fake
     until then.
   - That way, merging the bridge needs no code change in your files.
6. Config uses pydantic-settings. List any new env vars in your report under "Needs from main".
7. `/health` returns 200, because the ArmorIQ console probes it.

HUMAN STEPS:
- The user must have GEMINI_API_KEY and ELEVENLABS_API_KEY in .env. Ask if they're missing.
- Credits matter: develop in text mode, and use audio sparingly.

DONE MEANS:
- Unit tests with a `FakeGateway` covering allow, hold-then-approve, hold-timeout and block.
  They must prove:
  - the tool schemas reach the LLM
  - handlers route through the gateway
  - the hold path speaks first and waits in the background
  - barge-in during a hold doesn't call the tool twice
  - hanging up cancels the wait
- A live text-mode conversation (marked `live`, Gemini only, fake gateway) that completes a
  "check availability" turn and a "refund $40" turn.
- One short live audio check in the browser, with you guiding the user:
  - the mic input works
  - the voice output works
  - barge-in works

  Record the latency numbers you observe.
- `python scripts/check.py --changed` is green, the reviewer says PASS, and Codex says PASS
  (max 3 rounds).
- notes-drafts/voice.md is written in the AGENTS.md notes format.

Start by showing me your plan before editing.
