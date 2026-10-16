"""FastAPI app for the voice agent.

Endpoints:
- GET  /health                       200 for the ArmorIQ console probe and uptime checks
- GET  /client/                      Pipecat's prebuilt browser client (mic test page)
- POST /start, POST|PATCH /api/offer SmallWebRTC signalling used by the browser client
- WS   /ws                           raw PCM audio for the caller simulator
- POST /text/calls                   open a text-mode call (no STT/TTS, no ElevenLabs credits)
- POST /text/calls/{id}/turns        send one caller turn, get the agent's reply
- POST /text/calls/{id}/collect      fetch output that arrived later (a hold outcome)
- POST /text/calls/{id}/decision     demo only: the caller, as manager, decides their own hold
- DELETE /text/calls/{id}            hang up (cancels pending holds)

Run: `uv run --project apps/agent uvicorn countersign_agent.app:app --port 7860`
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import RedirectResponse
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.request_handler import (
    IceCandidate,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)
from pydantic import BaseModel, Field

from countersign_agent.bridge.manager_desk import ArmorIQManagerDesk, ManagerDesk
from countersign_agent.contracts import GatewayFactory
from countersign_agent.voice.config import AgentSettings
from countersign_agent.voice.fake_gateway import FakeGatewayFactory
from countersign_agent.voice.pipeline import run_audio_call
from countersign_agent.voice.session import LLMFactory, make_llm
from countersign_agent.voice.text_mode import TextReply, TextSession
from countersign_agent.voice.transports import simulator_transport, webrtc_transport

logger = logging.getLogger(__name__)


def load_factory(path: str) -> GatewayFactory:
    """Resolve GATEWAY_FACTORY ("module.path:attribute") to a GatewayFactory.

    The attribute may be a factory object or a zero-argument callable that returns one.
    """
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        raise ValueError(f"GATEWAY_FACTORY must look like 'module.path:attribute', got {path!r}")
    target: Any = getattr(importlib.import_module(module_name), attr)
    is_instance = hasattr(target, "open_call") and not isinstance(target, type)
    factory = target if is_instance else target()
    if not hasattr(factory, "open_call"):
        raise TypeError(f"{path} is not a GatewayFactory (no open_call)")
    if isinstance(factory, FakeGatewayFactory):
        logger.warning(
            "\n%s\nFAKE GATEWAY IN USE (%s): tool calls are NOT governed by ArmorIQ and NOT "
            "executed against hotel-mcp. Dev and tests only; never report results from it.\n%s",
            "!" * 78,
            path,
            "!" * 78,
        )
    return factory


class TextTurn(BaseModel):
    text: str = Field(min_length=1)
    wait_for_holds: bool = True


class TextCallOpened(BaseModel):
    call_id: str


class CollectRequest(BaseModel):
    wait_for_holds: bool = True


class HoldDecision(BaseModel):
    decision: Literal["approve", "reject"]
    # Which held tool, when more than one is waiting; otherwise the only one.
    tool: str | None = None


class HoldDecided(BaseModel):
    tool: str
    decision: Literal["approve", "reject"]
    armoriq_status: int


def default_manager_desk(settings: AgentSettings) -> ManagerDesk | None:
    """The demo desk only when DEMO_MANAGER_APPROVALS is on (see AgentSettings)."""
    if not settings.demo_manager_approvals:
        return None
    from countersign_agent.bridge.settings import BridgeSettings

    bridge = BridgeSettings()
    return ArmorIQManagerDesk(
        bridge.armoriq_api_key.get_secret_value(),
        bridge.armoriq_admin_email,
        os.environ.get("ARMORIQ_BACKEND_ENDPOINT", "https://api.armoriq.ai"),
    )


def create_app(
    settings: AgentSettings | None = None,
    factory: GatewayFactory | None = None,
    *,
    llm_factory: LLMFactory = make_llm,
    manager_desk: ManagerDesk | None = None,
) -> FastAPI:
    settings = settings or AgentSettings()
    gateway_factory = factory or load_factory(settings.gateway_factory)
    desk = manager_desk or default_manager_desk(settings)
    text_calls: dict[str, TextSession] = {}
    webrtc_sessions: set[str] = set()
    audio_tasks: set[asyncio.Task[None]] = set()
    webrtc = SmallWebRTCRequestHandler()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        for session in list(text_calls.values()):
            try:
                await session.close()
            except Exception:
                # Keep shutting the rest down; one broken call must not leak the others.
                logger.exception("closing text call %s failed", session.call_id)
        text_calls.clear()
        await webrtc.close()
        for task in list(audio_tasks):
            task.cancel()
        await asyncio.gather(*audio_tasks, return_exceptions=True)

    app = FastAPI(title="Countersign voice agent", lifespan=lifespan)
    app.state.settings = settings
    app.state.factory = gateway_factory
    app.state.text_calls = text_calls

    def start_audio_call(call_id: str, coro: Any) -> None:
        task = asyncio.create_task(coro, name=f"audio:{call_id}")
        audio_tasks.add(task)
        task.add_done_callback(audio_tasks.discard)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # --- Browser audio (SmallWebRTC + prebuilt client) ---

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/client/")

    @app.post("/start")
    async def start() -> dict[str, str]:
        session_id = str(uuid.uuid4())
        webrtc_sessions.add(session_id)
        return {"sessionId": session_id}

    async def handle_offer(offer: SmallWebRTCRequest) -> dict[str, str] | None:
        call_id = f"webrtc-{uuid.uuid4().hex[:8]}"

        async def on_connection(connection: SmallWebRTCConnection) -> None:
            start_audio_call(
                call_id,
                run_audio_call(call_id, webrtc_transport(connection), gateway_factory, settings),
            )

        return await webrtc.handle_web_request(offer, on_connection)

    @app.post("/api/offer")
    async def offer(request: SmallWebRTCRequest) -> dict[str, str] | None:
        return await handle_offer(request)

    @app.patch("/api/offer")
    async def ice_candidates(request: SmallWebRTCPatchRequest) -> dict[str, str]:
        await webrtc.handle_patch_request(request)
        return {"status": "success"}

    @app.api_route("/sessions/{session_id}/api/offer", methods=["POST", "PATCH"])
    async def session_offer(session_id: str, request: Request) -> Any:
        # The prebuilt client calls /start, then signals through this session path.
        if session_id not in webrtc_sessions:
            raise HTTPException(status_code=404, detail="unknown session")
        body = await request.json()
        if request.method == "POST":
            return await handle_offer(
                SmallWebRTCRequest(sdp=body["sdp"], type=body["type"], pc_id=body.get("pc_id"))
            )
        await webrtc.handle_patch_request(
            SmallWebRTCPatchRequest(
                pc_id=body["pc_id"],
                candidates=[IceCandidate(**c) for c in body.get("candidates", [])],
            )
        )
        return {"status": "success"}

    _mount_prebuilt_client(app)

    # --- Caller simulator audio ---

    @app.websocket("/ws")
    async def simulator(websocket: WebSocket) -> None:
        await websocket.accept()
        call_id = f"ws-{uuid.uuid4().hex[:8]}"
        await run_audio_call(call_id, simulator_transport(websocket), gateway_factory, settings)

    # --- Text mode ---

    def text_call(call_id: str) -> TextSession:
        session = text_calls.get(call_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"no text call {call_id}")
        return session

    @app.post("/text/calls", status_code=201)
    async def open_text_call() -> TextCallOpened:
        call_id = f"text-{uuid.uuid4().hex[:8]}"
        text_calls[call_id] = await TextSession.open(
            call_id, gateway_factory, settings, llm_factory=llm_factory
        )
        return TextCallOpened(call_id=call_id)

    @app.post("/text/calls/{call_id}/turns")
    async def text_turn(call_id: str, turn: TextTurn) -> TextReply:
        session = text_call(call_id)
        try:
            return await session.send(turn.text, wait_for_holds=turn.wait_for_holds)
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail="the agent did not finish in time") from exc

    @app.post("/text/calls/{call_id}/collect")
    async def text_collect(call_id: str, body: CollectRequest | None = None) -> TextReply:
        session = text_call(call_id)
        try:
            return await session.collect(wait_for_holds=body.wait_for_holds if body else True)
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail="the agent did not finish in time") from exc

    @app.post("/text/calls/{call_id}/decision")
    async def decide_hold(call_id: str, body: HoldDecision) -> HoldDecided:
        if desk is None:
            raise HTTPException(status_code=403, detail="manager decisions are not enabled")
        session = text_call(call_id)
        # Only this call's own held requests: the delegation id never comes from the browser.
        held = [h for h in session.core.router.held_requests if body.tool in (None, h.tool)]
        if not held:
            raise HTTPException(status_code=409, detail="nothing is waiting for a manager")
        result = await desk.decide(held[0], body.decision)
        if not result.ok:
            logger.warning("ArmorIQ refused the demo %s: %s", body.decision, result.body)
            raise HTTPException(status_code=502, detail="ArmorIQ did not accept the decision")
        return HoldDecided(
            tool=held[0].tool, decision=body.decision, armoriq_status=result.status_code
        )

    @app.delete("/text/calls/{call_id}", status_code=204)
    async def hang_up(call_id: str) -> None:
        session = text_call(call_id)
        del text_calls[call_id]
        await session.close()

    return app


def _mount_prebuilt_client(app: FastAPI) -> None:
    from pipecat_ai_small_webrtc_prebuilt.frontend import SmallWebRTCPrebuiltUI

    app.mount("/client", SmallWebRTCPrebuiltUI)


def main() -> None:
    """`uv run --project apps/agent python -m countersign_agent.app`"""
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = AgentSettings()
    uvicorn.run(create_app(settings), host=settings.agent_host, port=settings.agent_port)


if __name__ == "__main__":
    main()


def __getattr__(name: str) -> FastAPI:
    # `uvicorn countersign_agent.app:app` builds the app on first access, so importing this
    # module (e.g. in tests) does not read settings or load the gateway factory.
    if name == "app":
        built = create_app()
        globals()["app"] = built
        return built
    raise AttributeError(name)
