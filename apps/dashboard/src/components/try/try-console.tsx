"use client";

import { ArrowCounterClockwise, WarningCircle } from "@phosphor-icons/react";
import { Frame } from "@/components/frame";
import { DecisionLog } from "@/components/try/decision-log";
import { GuidedScript } from "@/components/try/guided-script";
import { ManagerCard } from "@/components/try/manager-card";
import { Transcript } from "@/components/try/transcript";
import { useAgentCall } from "@/lib/use-agent-call";

/** The live demo: a text call with the deployed agent, governed by ArmorIQ end to end. */
export function TryConsole() {
  const { lines, log, status, held, error, send, decide, reset } = useAgentCall();
  const busy =
    status === "thinking" || status === "held" || status === "deciding" || status === "connecting";

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[20rem_minmax(0,1fr)_22rem] lg:gap-5">
      <aside className="order-2 lg:order-1">
        <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.14em] text-dim">Try this, in order</p>
        <GuidedScript onSay={send} disabled={busy} />
      </aside>

      <Frame className="order-1 flex flex-col overflow-hidden lg:order-2 lg:h-[calc(100dvh-10rem)] lg:min-h-[36rem]">
        <div className="flex items-center justify-between border-b border-line px-5 py-3 md:px-7">
          <div className="flex items-center gap-2.5">
            <span
              className={`h-2 w-2 rounded-full ${
                status === "connecting" ? "animate-pulse bg-hold" : status === "error" ? "bg-block" : "bg-allow"
              }`}
            />
            <span className="text-sm text-text">The Larkspur, front desk</span>
            <span className="hidden font-mono text-[11px] text-dim sm:inline">
              {status === "connecting" ? "connecting to ArmorIQ…" : "text call"}
            </span>
          </div>
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
        </div>
        {error && (
          <p role="alert" className="flex items-center gap-2 border-b border-line bg-block/10 px-5 py-2.5 text-[13px] text-block md:px-7">
            <WarningCircle size={16} />
            {error}
          </p>
        )}
        {held && (
          // On small screens the side column sits below the steps; keep the decision in view.
          <div className="border-b border-line p-3 lg:hidden">
            <ManagerCard key={held} tool={held} deciding={status === "deciding"} onDecide={decide} />
          </div>
        )}
        <div className="min-h-0 flex-1">
          <Transcript lines={lines} status={status} onSend={send} />
        </div>
      </Frame>

      <aside className="order-3 space-y-4">
        {held && (
          <div className="hidden lg:block">
            <ManagerCard key={held} tool={held} deciding={status === "deciding"} onDecide={decide} />
          </div>
        )}
        <Frame className="p-5">
          <DecisionLog log={log} />
        </Frame>
      </aside>
    </div>
  );
}
