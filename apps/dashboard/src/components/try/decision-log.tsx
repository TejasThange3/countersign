"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { DecisionChip, type DecisionKind } from "@/components/decision-chip";
import type { Logged } from "@/lib/use-agent-call";

/** What the caller sees for each ArmorIQ verdict, once the action has settled. */
function verdict(r: Logged): { kind: DecisionKind; label: string } {
  if (r.decision === "allow") return { kind: "allow", label: "allow" };
  if (r.decision === "block" || r.decision === "unavailable") return { kind: "block", label: r.decision };
  if (r.outcome === "pending") return { kind: "hold", label: "hold" };
  if (r.outcome === "ran") return { kind: "allow", label: "approved" };
  if (r.reason === "rejected") return { kind: "block", label: "rejected" };
  return { kind: "block", label: "timed out" };
}

const OUTCOME: Record<Logged["outcome"], string> = {
  ran: "ran",
  pending: "waiting for a manager",
  not_run: "did not run",
  error: "failed",
};

export function DecisionLog({ log }: { log: Logged[] }) {
  const reduce = useReducedMotion();
  return (
    <div>
      <div className="flex items-center justify-between">
        <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-dim">ArmorIQ decisions</p>
        <span className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-allow">
          <span className="h-1.5 w-1.5 rounded-full bg-allow" />
          live
        </span>
      </div>
      {log.length === 0 ? (
        <p className="mt-4 text-[14px] leading-relaxed text-dim">
          Every action the agent tries appears here, with ArmorIQ&apos;s verdict, before it runs.
        </p>
      ) : (
        <ol className="mt-4 space-y-2">
          <AnimatePresence initial={false}>
            {[...log].reverse().map((r) => {
              const v = verdict(r);
              return (
                <motion.li
                  key={r.id}
                  layout={!reduce}
                  initial={reduce ? false : { opacity: 0, x: 12 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                  className="rounded-lg border border-line bg-ink px-3.5 py-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate font-mono text-[13px] text-text">{r.tool}</span>
                    <DecisionChip kind={v.kind} label={v.label} />
                  </div>
                  <p className="mt-1.5 font-mono text-[11px] text-dim">
                    {OUTCOME[r.outcome]}
                    {r.reason ? ` · ${r.reason}` : ""}
                    {r.plan_id ? ` · plan ${r.plan_id.slice(0, 8)}` : ""}
                  </p>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ol>
      )}
    </div>
  );
}
