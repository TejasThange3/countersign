"use client";

import { useState } from "react";
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from "motion/react";
import { Frame } from "@/components/frame";
import type { DecisionKind } from "@/components/decision-chip";

/** The live `countersign` policy on platform.armoriq.ai (docs/research/armoriq-policy-countersign.md). */
type Who = "stranger" | "guest";

const GROUPS: { name: string; tools: string[]; decision: Record<Who, DecisionKind> }[] = [
  {
    name: "Look things up",
    tools: ["verify_guest", "get_booking", "check_availability", "get_hotel_info", "get_cancellation_policy"],
    decision: { stranger: "allow", guest: "allow" },
  },
  {
    name: "Change a stay",
    tools: ["create_booking", "modify_booking_dates", "add_booking_note", "request_housekeeping", "cancel_own_booking"],
    decision: { stranger: "block", guest: "allow" },
  },
  {
    name: "Move money",
    tools: ["issue_refund", "apply_comp_credit", "waive_fee"],
    decision: { stranger: "block", guest: "hold" },
  },
  {
    name: "Sensitive",
    tools: ["export_guest_list", "cancel_any_booking", "delete_guest_profile", "grant_staff_access"],
    decision: { stranger: "block", guest: "block" },
  },
];

const TONE: Record<DecisionKind, { dot: string; text: string; chip: string; word: string }> = {
  allow: { dot: "bg-allow", text: "text-allow", chip: "border-allow/25 bg-allow/[0.06] text-text", word: "Allowed" },
  hold: { dot: "bg-hold", text: "text-hold", chip: "border-hold/40 bg-hold/[0.08] text-text", word: "Held for a manager" },
  block: { dot: "bg-block", text: "text-block", chip: "border-line text-dim line-through decoration-block/60", word: "Blocked" },
};

const WHO: { id: Who; label: string; sub: string }[] = [
  { id: "stranger", label: "Stranger", sub: "Not yet verified" },
  { id: "guest", label: "Verified guest", sub: "Booking ref + surname" },
];

export function Policy() {
  const [who, setWho] = useState<Who>("stranger");
  const reduce = useReducedMotion();

  return (
    <section id="policy" className="mx-auto max-w-[1400px] scroll-mt-20 px-4 py-28 md:px-8 md:py-36">
      <div className="grid grid-cols-1 gap-10 lg:grid-cols-[0.8fr_1.2fr] lg:gap-16">
        <div className="lg:sticky lg:top-28 lg:self-start">
          <h2 className="text-4xl font-medium leading-[1.05] tracking-[-0.03em] md:text-5xl">
            The rules live in ArmorIQ, not in the prompt.
          </h2>
          <p className="mt-5 max-w-[44ch] text-lg leading-relaxed text-muted">
            Same agent, same prompt. Switch who is calling and watch what the policy lets through.
            Anything not listed is refused by default.
          </p>

          <LayoutGroup>
            <div
              role="tablist"
              aria-label="Caller identity"
              className="mt-10 inline-grid grid-cols-2 rounded-full border border-line-strong bg-ink p-1"
            >
              {WHO.map((w) => (
                <button
                  key={w.id}
                  type="button"
                  role="tab"
                  aria-selected={who === w.id}
                  onClick={() => setWho(w.id)}
                  className="group relative cursor-pointer rounded-full px-5 py-2.5 text-left outline-none transition-transform duration-200 active:scale-[0.97] focus-visible:ring-2 focus-visible:ring-accent/60"
                >
                  {who === w.id && (
                    <motion.span
                      layoutId="who-pill"
                      className="absolute inset-0 rounded-full bg-accent"
                      transition={{ type: "spring", stiffness: 380, damping: 32 }}
                    />
                  )}
                  <span className={`relative block text-sm font-medium transition-colors ${who === w.id ? "text-ink" : "text-text group-hover:text-accent"}`}>
                    {w.label}
                  </span>
                  <span className={`relative block text-[11px] ${who === w.id ? "text-ink/70" : "text-dim"}`}>
                    {w.sub}
                  </span>
                </button>
              ))}
            </div>
          </LayoutGroup>
        </div>

        <Frame className="divide-y divide-line">
          {GROUPS.map((g) => {
            const d = g.decision[who];
            const tone = TONE[d];
            return (
              <div key={g.name} className="p-6 md:p-8">
                <div className="flex items-center justify-between gap-4">
                  <h3 className="text-lg font-medium tracking-[-0.015em]">{g.name}</h3>
                  <AnimatePresence mode="wait" initial={false}>
                    <motion.span
                      key={d}
                      initial={reduce ? false : { opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -6 }}
                      transition={{ duration: 0.22 }}
                      className={`inline-flex items-center gap-2 font-mono text-[12px] uppercase tracking-[0.12em] ${tone.text}`}
                    >
                      <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
                      {tone.word}
                    </motion.span>
                  </AnimatePresence>
                </div>
                <ul className="mt-5 flex flex-wrap gap-2">
                  {g.tools.map((t, i) => (
                    <motion.li
                      key={t}
                      animate={reduce ? undefined : { opacity: d === "block" ? 0.55 : 1 }}
                      transition={{ duration: 0.3, delay: i * 0.03 }}
                      className={`rounded-full border px-3 py-1 font-mono text-[12px] transition-colors duration-300 ${tone.chip}`}
                    >
                      {t}
                    </motion.li>
                  ))}
                </ul>
              </div>
            );
          })}
        </Frame>
      </div>
    </section>
  );
}
