## N. The voice agent: the receptionist on the phone

**Analogy.** Picture the hotel's receptionist on the phone. She listens (STT turns the caller's
voice into words), thinks about what to do (the LLM), and answers out loud (TTS). When she needs
something done she writes a slip and hands it through the hatch to the guard (the gateway; the
ArmorIQ bridge once it merges). She never opens the filing cabinets herself. Most slips come
back right away. When the guard says "the manager has to sign this one", she doesn't go silent:
she says "That needs a manager's approval, one moment", puts the caller on hold music, and keeps
listening. If the caller asks "hello, is my refund coming?", she says "still waiting on the
manager" and does *not* write a second slip. When the manager signs or refuses, she tells the
caller. If the caller hangs up, she tears up the waiting slip. In text mode (for practice) she
answers the same questions by chat instead of by phone: same brain, same hatch, no ears or voice.

**Technical explanation.**
- **Pipecat pipeline** (Pipecat = a Python framework that streams *frames* (audio chunks, text,
  control signals) through a chain of processors). Audio mode, per call:
  `transport in → STT → user context aggregator (Silero VAD + smart-turn) → Gemini → ElevenLabs
  TTS → transport out → assistant context aggregator`. *VAD* (voice activity detection) notices
  speech starting and stopping. *Smart-turn* is a small local model that decides when the caller
  has finished their turn. *Barge-in* is the caller talking over the bot: VAD start triggers an
  interruption that drops queued audio and cancels the running reply. This is the receptionist's
  ears, brain and mouth.
- **STT** is local **faster-whisper** (`distil-medium.en`, about 400 MB, chosen because the dev
  machine is short on RAM; set `WHISPER_MODEL=distil-large-v3` for better accuracy) on the RTX
  4060, so listening costs no credits. Faster-whisper loaded CUDA with no extra DLL setup, because torch ships the CUDA
  libraries. `STT_PROVIDER=elevenlabs` switches to ElevenLabs Scribe. **TTS** is ElevenLabs
  `eleven_flash_v2_5`.
- **Tools come only from the gateway.** `voice/tools.py` turns each `ToolSpec` from
  `gateway.tool_specs()` into a Pipecat `FunctionSchema`. Every one has the same handler,
  `ToolRouter.handle`, which calls `gateway.call(...)`. There is no other path to a tool: this is
  the hatch.
- **Holds** (`voice/holds.py`, `ToolRouter`). When `gateway.call` returns outcome `PENDING`:
  1. a fixed line is spoken immediately;
  2. the LLM gets a "PENDING" result with `run_llm=False`, so it doesn't talk over that line;
  3. a background `asyncio` task plays filler and awaits `gateway.wait()`;
  4. the final outcome is appended to the context as a developer message and the LLM speaks it.
  A timeout, or any error while waiting, counts as a refusal (fail closed). While the hold is
  pending, another call to the same tool *name* (any arguments, so 250 vs 250.0 can't slip
  through) gets "STILL_WAITING" and never reaches the gateway. `close()` (hangup) cancels every
  wait before the gateway closes.
- **Talking over the bot never loses an action.** Pipecat cancels a tool handler on barge-in.
  For acting tools (anything not a read) the gateway call runs in a router-owned task behind
  `asyncio.shield`, so it finishes anyway; its outcome is added to the context afterwards with
  "already processed, do not call again", and a repeat call while it runs is a DUPLICATE. Only
  hangup cancels it. Reads are simply cancelled, since they change nothing.
- **Filler costs no TTS credits per hold.** `voice/filler.py` synthesizes "Still checking with
  the manager" once, caches the raw PCM in `~/.cache/countersign/` (keyed by voice and model) and
  replays it. Without a key it plays a generated two-note tone.
- **Text mode** (`voice/text_mode.py`, `TextSession`). The same `CallCore` (LLM, context, router,
  metrics) runs in a pipeline with no transport, STT or TTS. A turn is a user message appended
  to the context. An observer collects the reply and decides when the agent is idle (no reply
  streaming, no tool call in flight, no inference about to start, and optionally no hold
  pending). HTTP: `POST /text/calls`, `POST /text/calls/{id}/turns`
  (`{text, wait_for_holds}`), `POST /text/calls/{id}/collect`, `DELETE /text/calls/{id}`. Each
  reply lists messages, tool results, pending holds, per-turn metrics and the model(s) used.
- **Gemini with an honest fallback** (`voice/llm.py`). Primary `gemini-3.8-flash`, fallback
  `gemini-3.5-flash`. On a 429 (rate limit) it backs off and retries. On 404/500/503, or when the
  model accepts a request but sends nothing for 10 s, it switches to the fallback and skips the
  failing model for 120 s (a *cooldown*). The google-genai SDK's own retries are turned off: they
  hid a 503 for over a minute. Every turn records which model answered and every switch is
  logged. `GEMINI_FALLBACK_MODEL=` (empty) pins one model for eval runs, so a down model fails
  loudly instead of mixing models.
- **Metrics** (`voice/metrics.py`). `enable_metrics=True`. An observer records per turn: STT
  final (caller stopped → final transcript), LLM TTFT (first answer token, thinking included),
  TTS TTFB (first audio byte), user→bot latency, and models used.
- **Gateway wiring.** `app.py` loads `GATEWAY_FACTORY` ("module:attribute"). The default is the
  dev-only `FakeGatewayFactory`, which logs a loud banner because its decisions are scripted, not
  ArmorIQ's. When the bridge merges, `GATEWAY_FACTORY=countersign_agent.bridge:factory` is the
  only change.
- **One system prompt** (`voice/prompts.py`) for every mode. It says nothing about ArmorIQ,
  policies or limits, so nothing there can be probed and the with/without comparison is fair.

**Where it lives.** `apps/agent/src/countersign_agent/app.py`,
`apps/agent/src/countersign_agent/voice/` (`pipeline.py`, `text_mode.py`, `session.py`,
`holds.py`, `tools.py`, `llm.py`, `metrics.py`, `filler.py`, `transports.py`, `prompts.py`,
`fake_gateway.py`, `config.py`), tests in `apps/agent/tests/voice/` and
`apps/agent/tests/test_app.py`.

**How to check it works.**
- Unit tests (no network): `uv run --project apps/agent pytest -q -m "not live"` → all pass.
- Live text test (Gemini, fake gateway, no ElevenLabs):
  `uv run --project apps/agent pytest -m live tests/voice/test_live_text.py -s` → availability
  and a $40 refund complete.
- Server: `uv run --project apps/agent python -m countersign_agent.app`, then
  `curl localhost:7860/health` → `{"status":"ok"}`. Open `http://localhost:7860/client/` and
  click Connect to talk to the agent.

Glossary additions: frame (Pipecat), VAD, smart-turn, barge-in, TTFT, TTFB, cooldown, hold
filler, text mode.
