"use client";

import { useEffect, useRef, useState } from "react";
import { Microphone, PhoneDisconnect } from "@phosphor-icons/react";
import type { VoiceCall } from "@/lib/voice-call";
import type { VoiceStatus } from "@/lib/use-voice-call";

const BARS = 5;

/** Start or end the voice call, with a live microphone meter and who is talking. */
export function VoiceControls({
  status,
  call,
  onStart,
  onHangUp,
}: {
  status: VoiceStatus;
  call: { current: VoiceCall | null };
  onStart: () => void;
  onHangUp: () => void;
}) {
  const meter = useRef<HTMLDivElement>(null);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const live = status === "live";

  // Read the level straight from the call each frame; no React state per frame.
  useEffect(() => {
    if (!live) return;
    let frame = 0;
    const tick = () => {
      const level = call.current?.micLevel.value ?? 0;
      meter.current?.querySelectorAll<HTMLSpanElement>("span").forEach((bar, i) => {
        const on = level * BARS * 1.6 > i;
        bar.style.transform = `scaleY(${on ? 1 : 0.3})`;
        bar.style.opacity = on ? "1" : "0.35";
      });
      setAgentSpeaking(!!call.current?.agentSpeaking);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [live, call]);

  return (
    <div className="flex items-center justify-between gap-4 border-t border-line p-3 pl-5">
      <div className="flex min-w-0 items-center gap-3">
        <div ref={meter} className="flex h-5 items-center gap-[3px]" aria-hidden>
          {Array.from({ length: BARS }, (_, i) => (
            <span
              key={i}
              className="h-full w-[3px] origin-center rounded-full bg-accent transition-[transform,opacity] duration-75"
              style={{ transform: "scaleY(0.3)", opacity: 0.35 }}
            />
          ))}
        </div>
        <p className="truncate text-[13px] text-muted">
          {status === "connecting"
            ? "Opening a secure ArmorIQ session… allow the microphone if asked"
            : live
              ? agentSpeaking
                ? "Agent speaking. Talk over it to interrupt."
                : "Listening…"
              : status === "ended"
                ? "Call ended."
                : "Voice call with the front desk"}
        </p>
      </div>
      {live || status === "connecting" ? (
        <button
          type="button"
          onClick={onHangUp}
          className="inline-flex h-11 shrink-0 cursor-pointer items-center gap-2 rounded-xl bg-block px-4 text-sm font-medium text-ink transition-transform duration-200 active:scale-[0.97]"
        >
          <PhoneDisconnect size={16} weight="fill" />
          Hang up
        </button>
      ) : (
        <button
          type="button"
          onClick={onStart}
          className="inline-flex h-11 shrink-0 cursor-pointer items-center gap-2 rounded-xl bg-accent px-4 text-sm font-medium text-ink transition-[background-color,transform] duration-200 hover:bg-accent-hover active:scale-[0.97]"
        >
          <Microphone size={16} weight="fill" />
          {status === "ended" ? "Call again" : "Start voice call"}
        </button>
      )}
    </div>
  );
}
