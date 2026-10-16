"use client";

import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Check, Info, X } from "@phosphor-icons/react";
import type { ManagerDecision } from "@/lib/agent";

/** Matches the agent's HOLD_TIMEOUT_S: after this, the request is refused on its own. */
const HOLD_SECONDS = 60;

const TOOL_LABEL: Record<string, string> = {
  issue_refund: "Refund",
  apply_comp_credit: "Credit",
  waive_fee: "Fee waiver",
};

export function ManagerCard({
  tool,
  deciding,
  onDecide,
}: {
  tool: string;
  deciding: boolean;
  onDecide: (d: ManagerDecision) => void;
}) {
  const reduce = useReducedMotion();
  const [left, setLeft] = useState(HOLD_SECONDS);

  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => {
      setLeft(Math.max(0, HOLD_SECONDS - Math.floor((Date.now() - started) / 1000)));
    }, 250);
    return () => clearInterval(timer);
  }, []);

  return (
    <motion.section
      initial={reduce ? false : { opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 320, damping: 28 }}
      aria-label="Manager decision"
      className="rounded-xl border border-hold/40 bg-hold/[0.06] p-5"
    >
      <div className="flex items-center justify-between gap-3">
        <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-hold">Held by ArmorIQ</p>
        <span className="font-mono text-[12px] tabular-nums text-muted">{left}s</span>
      </div>
      <h3 className="mt-3 text-lg font-medium tracking-[-0.015em]">
        {TOOL_LABEL[tool] ?? tool} waiting for a manager
      </h3>
      <p className="mt-1 font-mono text-[12px] text-dim">{tool}</p>

      <div className="mt-4 h-1 overflow-hidden rounded-full bg-line">
        <div
          className="h-full origin-left bg-hold transition-transform duration-300 ease-linear"
          style={{ transform: `scaleX(${left / HOLD_SECONDS})` }}
        />
      </div>

      <div className="mt-5 grid grid-cols-2 gap-2">
        <button
          type="button"
          disabled={deciding}
          onClick={() => onDecide("approve")}
          className="inline-flex h-11 cursor-pointer items-center justify-center gap-2 rounded-xl bg-accent text-sm font-medium text-ink transition-[background-color,transform] duration-200 hover:bg-accent-hover active:scale-[0.97] disabled:cursor-wait disabled:opacity-60"
        >
          <Check size={16} weight="bold" />
          Approve
        </button>
        <button
          type="button"
          disabled={deciding}
          onClick={() => onDecide("reject")}
          className="inline-flex h-11 cursor-pointer items-center justify-center gap-2 rounded-xl border border-line-strong text-sm font-medium text-text transition-[background-color,transform] duration-200 hover:bg-panel-2 active:scale-[0.97] disabled:cursor-wait disabled:opacity-60"
        >
          <X size={16} weight="bold" />
          Reject
        </button>
      </div>

      <p className="mt-5 flex gap-2.5 text-[13px] leading-relaxed text-muted">
        <Info size={16} className="mt-0.5 shrink-0 text-hold" />
        <span>
          <span className="text-text">You&apos;re playing the manager.</span> In a real hotel this request goes
          to a human manager, who approves or rejects it in the ArmorIQ console. So you can test the full
          flow, this demo hands that decision to you. Your click goes to ArmorIQ&apos;s real approval API and
          is recorded in its audit log; the agent never decides for itself. No answer in {HOLD_SECONDS}{" "}
          seconds means it&apos;s refused.
        </span>
      </p>
    </motion.section>
  );
}
