"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { agent, AgentError, type ManagerDecision } from "@/lib/agent";
import type { Line, Logged } from "@/lib/use-agent-call";
import { VoiceCall, type VoiceEvent } from "@/lib/voice-call";

export type VoiceStatus = "idle" | "connecting" | "live" | "ended" | "error";

/** One website voice call: transcript, ArmorIQ decisions and a held request, from live events. */
export function useVoiceCall() {
  const [lines, setLines] = useState<Line[]>([]);
  const [log, setLog] = useState<Logged[]>([]);
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [held, setHeld] = useState<string | null>(null);
  const [deciding, setDeciding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const call = useRef<VoiceCall | null>(null);
  const callId = useRef<string | null>(null);
  const nextId = useRef(0);

  const line = useCallback((who: Line["who"], text: string) => {
    setLines((prev) => [...prev, { id: nextId.current++, who, text }]);
  }, []);

  const onEvent = useCallback(
    (e: VoiceEvent) => {
      switch (e.type) {
        case "call":
          callId.current = e.call_id;
          setStatus("live");
          break;
        case "busy":
          setError("Every voice line is busy right now. Try the text call, or again in a minute.");
          break;
        case "caller":
        case "agent":
          line(e.type, e.text);
          break;
        case "decision":
          setLog((prev) => [
            ...prev,
            {
              ...e,
              content: "",
              delegation_id: null,
              armoriq_mode: "live",
              latency_ms: 0,
              id: nextId.current++,
              at: Date.now(),
            },
          ]);
          break;
        case "held":
          setHeld(e.tool);
          break;
        case "settled":
          setHeld(null);
          setDeciding(false);
          break;
      }
    },
    [line],
  );

  const start = useCallback(async () => {
    if (call.current) return;
    setError(null);
    setLines([]);
    setLog([]);
    setHeld(null);
    setStatus("connecting");
    const voice = new VoiceCall({
      onEvent,
      onEnd: (reason) => {
        call.current = null;
        callId.current = null;
        setHeld(null);
        setDeciding(false);
        setStatus((s) => (s === "error" ? s : "ended"));
        if (reason === "error") setError("The call dropped. Check your connection and call again.");
      },
    });
    call.current = voice;
    try {
      await voice.start();
    } catch (e) {
      call.current = null;
      setStatus("error");
      setError(
        e instanceof DOMException && e.name === "NotAllowedError"
          ? "Microphone access was blocked. Allow it in your browser, or use the text call."
          : "Couldn't start the call. Check your microphone and connection.",
      );
      voice.hangUp();
    }
  }, [onEvent]);

  const hangUp = useCallback(() => call.current?.hangUp(), []);

  const decide = useCallback(
    async (decision: ManagerDecision) => {
      const id = callId.current;
      if (!id || !held || deciding) return;
      setDeciding(true);
      try {
        await agent.decideCall(id, decision);
        line("note", decision === "approve" ? "You approved it in ArmorIQ." : "You rejected it in ArmorIQ.");
      } catch (e) {
        setDeciding(false);
        line(
          "note",
          e instanceof AgentError && e.status === 409
            ? "That request was already settled."
            : "ArmorIQ didn't accept the decision; the request will time out safely.",
        );
      }
    },
    [held, deciding, line],
  );

  // Leaving the page hangs up.
  useEffect(() => () => call.current?.hangUp(), []);

  return { lines, log, status, held, deciding, error, start, hangUp, decide, call };
}
