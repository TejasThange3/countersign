"use client";

import { type ReactNode, useState } from "react";
import { LayoutGroup, motion } from "motion/react";
import { ArrowCounterClockwise, WarningCircle } from "@phosphor-icons/react";
import { Frame } from "@/components/frame";
import { DecisionLog } from "@/components/try/decision-log";
import { GuidedScript } from "@/components/try/guided-script";
import { ManagerCard } from "@/components/try/manager-card";
import { Transcript } from "@/components/try/transcript";
import { VoiceControls } from "@/components/try/voice-controls";
import type { ManagerDecision } from "@/lib/agent";
import { type Logged, useAgentCall } from "@/lib/use-agent-call";
import { useVoiceCall } from "@/lib/use-voice-call";

type Mode = "voice" | "text";

/** The live demo. Each mode owns its call, so switching modes hangs up the other one. */
export function TryConsole() {
  const [mode, setMode] = useState<Mode>("voice");
  const toggle = <ModeSwitch mode={mode} onChange={setMode} />;
  return mode === "voice" ? <VoiceConsole toggle={toggle} /> : <TextConsole toggle={toggle} />;
}

function TextConsole({ toggle }: { toggle: ReactNode }) {
  const { lines, log, status, held, error, send, decide, reset } = useAgentCall();
  const busy = status === "thinking" || status === "held" || status === "deciding" || status === "connecting";
  return (
    <Shell
      toggle={toggle}
      label={status === "connecting" ? "connecting to ArmorIQ…" : "text call"}
      dot={status === "connecting" ? "connecting" : status === "error" ? "error" : "live"}
      error={error}
      script={<GuidedScript onSay={send} disabled={busy} />}
      scriptTitle="Try this, in order"
      action={
        <button
          type="button"
          onClick={reset}
          aria-label="New call"
          disabled={status === "connecting"}
          className="inline-flex cursor-pointer items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] text-muted transition-colors hover:text-text disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ArrowCounterClockwise size={14} />
          <span className="hidden sm:inline">New call</span>
        </button>
      }
      held={held}
      deciding={status === "deciding"}
      onDecide={decide}
      log={log}
    >
      <Transcript lines={lines} status={status} onSend={send} />
    </Shell>
  );
}

function VoiceConsole({ toggle }: { toggle: ReactNode }) {
  const v = useVoiceCall();
  return (
    <Shell
      toggle={toggle}
      label={v.status === "live" ? "voice call" : v.status === "connecting" ? "dialling…" : "voice"}
      dot={v.status === "live" ? "live" : v.status === "connecting" ? "connecting" : v.status === "error" ? "error" : "idle"}
      error={v.error}
      script={<GuidedScript />}
      scriptTitle="Say these, in order"
      held={v.held}
      deciding={v.deciding}
      onDecide={v.decide}
      log={v.log}
    >
      <Transcript
        lines={v.lines}
        status="ready"
        onSend={() => undefined}
        empty="Start the call and speak naturally. Read the steps aloud, or say anything. Headphones help."
        footer={<VoiceControls status={v.status} call={v.call} onStart={v.start} onHangUp={v.hangUp} />}
      />
    </Shell>
  );
}

const DOT = {
  idle: "bg-dim",
  connecting: "animate-pulse bg-hold",
  live: "bg-allow",
  error: "bg-block",
} as const;

function Shell({
  toggle,
  label,
  dot,
  error,
  action,
  script,
  scriptTitle,
  held,
  deciding,
  onDecide,
  log,
  children,
}: {
  toggle: ReactNode;
  label: string;
  dot: keyof typeof DOT;
  error: string | null;
  action?: ReactNode;
  script: ReactNode;
  scriptTitle: string;
  held: string | null;
  deciding: boolean;
  onDecide: (d: ManagerDecision) => void;
  log: Logged[];
  children: ReactNode;
}) {
  const card = held && <ManagerCard key={held} tool={held} deciding={deciding} onDecide={onDecide} />;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[20rem_minmax(0,1fr)_22rem] lg:gap-5">
      <aside className="order-2 lg:order-1">
        <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.14em] text-dim">{scriptTitle}</p>
        {script}
      </aside>

      <Frame className="order-1 flex flex-col overflow-hidden lg:order-2 lg:h-[calc(100dvh-10rem)] lg:min-h-[36rem]">
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5 md:px-5">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[dot]}`} />
            <span className="truncate text-sm text-text">The Larkspur</span>
            <span className="hidden font-mono text-[11px] text-dim sm:inline">{label}</span>
          </div>
          <div className="flex items-center gap-1">
            {action}
            {toggle}
          </div>
        </div>
        {error && (
          <p role="alert" className="flex items-center gap-2 border-b border-line bg-block/10 px-5 py-2.5 text-[13px] text-block">
            <WarningCircle size={16} className="shrink-0" />
            {error}
          </p>
        )}
        {card && <div className="border-b border-line p-3 lg:hidden">{card}</div>}
        <div className="min-h-0 flex-1">{children}</div>
      </Frame>

      <aside className="order-3 space-y-4">
        {card && <div className="hidden lg:block">{card}</div>}
        <Frame className="p-5">
          <DecisionLog log={log} />
        </Frame>
      </aside>
    </div>
  );
}

function ModeSwitch({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  return (
    <LayoutGroup id="call-mode">
      <div role="tablist" aria-label="Call type" className="inline-flex rounded-full border border-line-strong bg-ink p-0.5">
        {(["voice", "text"] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            onClick={() => onChange(m)}
            className="relative cursor-pointer rounded-full px-3 py-1 text-[12px] font-medium capitalize outline-none transition-transform duration-200 active:scale-[0.97] focus-visible:ring-2 focus-visible:ring-accent/60"
          >
            {mode === m && (
              <motion.span
                layoutId="call-mode-pill"
                className="absolute inset-0 rounded-full bg-accent"
                transition={{ type: "spring", stiffness: 380, damping: 32 }}
              />
            )}
            <span className={`relative ${mode === m ? "text-ink" : "text-muted hover:text-text"}`}>{m}</span>
          </button>
        ))}
      </div>
    </LayoutGroup>
  );
}
