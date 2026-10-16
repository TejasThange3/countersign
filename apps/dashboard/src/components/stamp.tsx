"use client";

import { motion, useReducedMotion } from "motion/react";
import type { DecisionKind } from "@/components/decision-chip";

const TONE: Record<DecisionKind, string> = {
  allow: "text-allow border-allow/60",
  hold: "text-hold border-hold/60",
  block: "text-block border-block/60",
};

/**
 * A decision rendered as an inked rubber stamp: it drops in oversized and slightly rotated, then
 * settles, the way a countersignature lands on paper. Static under reduced motion.
 */
export function Stamp({
  kind,
  label,
  delay = 0,
}: {
  kind: DecisionKind;
  label?: string;
  delay?: number;
}) {
  const reduce = useReducedMotion();
  const rotate = kind === "block" ? -7 : kind === "hold" ? 4 : -3;
  return (
    <motion.span
      initial={reduce ? false : { opacity: 0, scale: 1.9, rotate: rotate * 2.5 }}
      whileInView={{ opacity: 1, scale: 1, rotate }}
      viewport={{ once: true, amount: 0.8 }}
      transition={{ type: "spring", stiffness: 420, damping: 22, delay }}
      className={`stamp inline-flex select-none items-center rounded-[4px] border-2 px-2 py-0.5 font-mono text-[11px] font-semibold uppercase tracking-[0.14em] ${TONE[kind]}`}
    >
      {label ?? kind}
    </motion.span>
  );
}
