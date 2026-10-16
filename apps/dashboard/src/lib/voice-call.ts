/**
 * A browser voice call with the agent over its /voice WebSocket
 * (apps/agent/src/countersign_agent/voice/browser_events.py documents the events).
 *
 *   browser -> agent   binary, 16 kHz mono PCM16 (from public/audio/mic-capture.js)
 *   agent -> browser   binary, 24 kHz mono PCM16 to play; JSON text events
 */

import { AGENT_URL } from "@/lib/agent";

const OUT_RATE = 24000;

export type VoiceEvent =
  | { type: "call"; call_id: string }
  | { type: "busy" }
  | { type: "caller" | "agent"; text: string }
  | { type: "interrupt" }
  | {
      type: "decision";
      tool: string;
      decision: "allow" | "hold" | "block" | "unavailable";
      outcome: "ran" | "pending" | "not_run" | "error";
      reason: string | null;
      plan_id: string | null;
    }
  | { type: "held" | "settled"; tool: string };

export type VoiceHandlers = {
  onEvent: (event: VoiceEvent) => void;
  onEnd: (reason: "hangup" | "closed" | "error") => void;
};

export class VoiceCall {
  private ws: WebSocket | null = null;
  private mic: MediaStream | null = null;
  private inCtx: AudioContext | null = null;
  private outCtx: AudioContext | null = null;
  private playing = new Set<AudioBufferSourceNode>();
  private playhead = 0;
  private ended = false;
  /** Microphone level, 0-1, for the on-screen meter. */
  readonly micLevel = { value: 0 };

  constructor(private readonly handlers: VoiceHandlers) {}

  /** Asks for the microphone, then dials. Rejects if the microphone is refused. */
  async start(): Promise<void> {
    this.mic = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    this.outCtx = new AudioContext({ sampleRate: OUT_RATE });
    this.inCtx = new AudioContext();
    await this.inCtx.audioWorklet.addModule("/audio/mic-capture.js");

    const ws = new WebSocket(`${AGENT_URL.replace(/^http/, "ws")}/voice`);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onmessage = (msg) => {
      if (typeof msg.data === "string") this.onText(msg.data);
      else this.play(msg.data as ArrayBuffer);
    };
    ws.onclose = () => this.finish("closed");
    ws.onerror = () => this.finish("error");
    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => resolve();
      ws.addEventListener("error", () => reject(new Error("could not reach the agent")), { once: true });
    });

    const source = this.inCtx.createMediaStreamSource(this.mic);
    const capture = new AudioWorkletNode(this.inCtx, "mic-capture");
    capture.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(e.data);
      const samples = new Int16Array(e.data);
      let peak = 0;
      for (const s of samples) peak = Math.max(peak, Math.abs(s));
      this.micLevel.value = peak / 0x7fff;
    };
    source.connect(capture);
  }

  /** True while agent audio is still queued to play. */
  get agentSpeaking(): boolean {
    return !!this.outCtx && this.playhead > this.outCtx.currentTime;
  }

  hangUp(): void {
    this.finish("hangup");
  }

  private onText(raw: string) {
    let event: VoiceEvent;
    try {
      event = JSON.parse(raw) as VoiceEvent;
    } catch {
      return;
    }
    if (event.type === "interrupt") this.stopPlayback();
    this.handlers.onEvent(event);
  }

  private play(buffer: ArrayBuffer) {
    const ctx = this.outCtx;
    if (!ctx || buffer.byteLength < 2) return;
    const pcm = new Int16Array(buffer);
    const audio = ctx.createBuffer(1, pcm.length, OUT_RATE);
    const channel = audio.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 0x8000;
    const node = ctx.createBufferSource();
    node.buffer = audio;
    node.connect(ctx.destination);
    // Back to back with what is already queued, so chunks play without gaps.
    const at = Math.max(ctx.currentTime + 0.02, this.playhead);
    node.start(at);
    this.playhead = at + audio.duration;
    this.playing.add(node);
    node.onended = () => this.playing.delete(node);
  }

  /** The caller talked over the agent: drop everything still queued. */
  private stopPlayback() {
    for (const node of this.playing) {
      try {
        node.stop();
      } catch {
        // Already stopped.
      }
    }
    this.playing.clear();
    this.playhead = 0;
  }

  private finish(reason: "hangup" | "closed" | "error") {
    if (this.ended) return;
    this.ended = true;
    this.stopPlayback();
    this.mic?.getTracks().forEach((t) => t.stop());
    void this.inCtx?.close().catch(() => undefined);
    void this.outCtx?.close().catch(() => undefined);
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) this.ws.close();
    this.micLevel.value = 0;
    this.handlers.onEnd(reason);
  }
}
