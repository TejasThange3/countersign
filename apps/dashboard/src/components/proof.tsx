"use client";

import { useState } from "react";
import Image from "next/image";
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from "motion/react";
import { Frame } from "@/components/frame";
import { Stamp } from "@/components/stamp";
import type { DecisionKind } from "@/components/decision-chip";

const SHOTS: {
  id: string;
  tab: string;
  kind: DecisionKind;
  src: string;
  w: number;
  h: number;
  caption: string;
}[] = [
  {
    id: "allow",
    tab: "Allowed",
    kind: "allow",
    src: "/proof/armoriq-allow.png",
    w: 2411,
    h: 1022,
    caption: "get_hotel_info for a guest, authorised by the policy and completed.",
  },
  {
    id: "block",
    tab: "Blocked",
    kind: "block",
    src: "/proof/armoriq-block.png",
    w: 2430,
    h: 1049,
    caption: "export_guest_list refused by ArmorIQ. It never reached the hotel server.",
  },
  {
    id: "hold",
    tab: "Held, then approved",
    kind: "hold",
    src: "/proof/armoriq-hold-approved.png",
    w: 2391,
    h: 1146,
    caption: "A refund paused for a human. A manager countersigned it, then it ran.",
  },
];

/**
 * Real ArmorIQ console screenshots in one viewer: a tab per decision, one large image at a time
 * (readable, instead of three thumbnails), crossfading between them.
 */
export function Proof() {
  const [active, setActive] = useState(SHOTS[0].id);
  const reduce = useReducedMotion();
  const shot = SHOTS.find((s) => s.id === active) ?? SHOTS[0];

  return (
    <section id="proof" className="mx-auto max-w-[1400px] scroll-mt-20 px-4 py-28 md:px-8 md:py-36">
      <div className="flex flex-col gap-8 md:flex-row md:items-end md:justify-between">
        <h2 className="max-w-[18ch] text-4xl font-medium leading-[1.05] tracking-[-0.03em] md:text-5xl">
          Straight from the ArmorIQ console.
        </h2>

        <LayoutGroup>
          <div
            role="tablist"
            aria-label="ArmorIQ decision"
            className="inline-flex w-fit flex-wrap gap-1 rounded-full border border-line-strong bg-ink p-1"
          >
            {SHOTS.map((s) => (
              <button
                key={s.id}
                type="button"
                role="tab"
                aria-selected={active === s.id}
                onClick={() => setActive(s.id)}
                className="group relative rounded-full px-4 py-2 text-sm outline-none transition-transform duration-200 active:scale-[0.97] focus-visible:ring-2 focus-visible:ring-accent/60"
              >
                {active === s.id && (
                  <motion.span
                    layoutId="proof-pill"
                    className="absolute inset-0 rounded-full bg-accent"
                    transition={{ type: "spring", stiffness: 380, damping: 32 }}
                  />
                )}
                <span
                  className={`relative font-medium transition-colors ${
                    active === s.id ? "text-ink" : "text-muted group-hover:text-text"
                  }`}
                >
                  {s.tab}
                </span>
              </button>
            ))}
          </div>
        </LayoutGroup>
      </div>

      <Frame className="mt-12 overflow-hidden">
        {/* Browser-window chrome so the screenshot reads as a real product surface. */}
        <div className="flex items-center gap-4 border-b border-line px-5 py-3">
          <div className="flex gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-line-strong" />
            <span className="h-2.5 w-2.5 rounded-full bg-line-strong" />
            <span className="h-2.5 w-2.5 rounded-full bg-line-strong" />
          </div>
          <span className="truncate rounded-md border border-line bg-ink px-3 py-1 font-mono text-[12px] text-dim">
            platform.armoriq.ai / intent
          </span>
        </div>

        <div className="relative bg-ink" style={{ aspectRatio: `${SHOTS[2].w} / ${SHOTS[2].h}` }}>
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.div
              key={shot.id}
              initial={reduce ? false : { opacity: 0, scale: 1.01 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
              className="absolute inset-0 flex items-start justify-center"
            >
              <Image
                src={shot.src}
                alt={shot.caption}
                width={shot.w}
                height={shot.h}
                className="h-auto w-full"
                sizes="(min-width: 1400px) 1340px, 100vw"
                priority={shot.id === SHOTS[0].id}
              />
            </motion.div>
          </AnimatePresence>
        </div>

        <div className="flex flex-col gap-3 border-t border-line px-5 py-4 sm:flex-row sm:items-center sm:justify-between md:px-7">
          <p className="text-[15px] text-muted">{shot.caption}</p>
          <Stamp key={shot.id} kind={shot.kind} label={shot.tab.split(",")[0]} />
        </div>
      </Frame>
    </section>
  );
}
