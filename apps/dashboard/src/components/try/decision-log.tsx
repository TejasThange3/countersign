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

const READS = new Set(["get_booking", "check_availability", "get_hotel_info", "get_cancellation_policy"]);
const MONEY = new Set(["issue_refund", "apply_comp_credit", "waive_fee"]);

/** "What you just saw", in one sentence, for a judge who hasn't read the docs. */
export function explain(r: Logged): string {
  if (r.reason === "verify_locked_out")
    return "Too many wrong guesses: verification is locked for the rest of this call.";
  if (r.decision === "unavailable")
    return "ArmorIQ couldn't be reached, so the action was refused. It fails closed.";
  if (r.decision === "block")
    return "ArmorIQ refused this before it reached the hotel's systems. The model asked; the policy said no.";
  if (r.decision === "hold") {
    if (r.outcome === "pending")
      return "Held by ArmorIQ. Nothing moves until a manager decides, and here that's you.";
    if (r.outcome === "ran")
      return "Approved by a manager in ArmorIQ, so it ran. The decision is in ArmorIQ's audit log.";
    if (r.reason === "rejected") return "The manager rejected it, so it never ran.";
    return "No manager answered in time, so it was refused. Silence never counts as a yes.";
  }
  if (r.tool === "verify_guest")
    return "Identity check. Only this, never what the caller claims, changes whose booking the agent may touch.";
  if (READS.has(r.tool)) return "A read-only lookup. ArmorIQ allowed it, and nothing changed.";
  if (MONEY.has(r.tool)) return "ArmorIQ allowed this money action.";
  return "A change to a verified guest's own stay. ArmorIQ checked it against the policy first.";
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
                  <p className="mt-2 text-[13px] leading-snug text-muted">{explain(r)}</p>
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
