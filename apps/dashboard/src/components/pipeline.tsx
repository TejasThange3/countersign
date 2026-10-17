"use client";

import { useRef, useState } from "react";
import {
  motion,
  useMotionValueEvent,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform,
} from "motion/react";
import { Microphone, Waveform, Brain, ShieldCheck, SealCheck, Database } from "@phosphor-icons/react";

const STAGES = [
  {
    icon: Microphone,
    name: "Caller",
    detail:
      "Speaks in the browser; audio streams to the agent over a WebSocket. The caller can cut in at any time.",
  },
  {
    icon: Waveform,
    name: "Speech to text",
    detail:
      "Whisper large-v3-turbo on Groq, with ElevenLabs Scribe as a fallback. Silero voice detection decides when someone is speaking.",
  },
  {
    icon: Brain,
    name: "Language model",
    detail: "gpt-oss-120b on Groq chooses which hotel tool to call. It proposes actions but never runs them.",
  },
  {
    icon: ShieldCheck,
    name: "Countersign bridge",
    detail:
      "Owns the caller's identity, injects the verified guest id, and sends every tool call to ArmorIQ first.",
  },
  {
    icon: SealCheck,
    name: "ArmorIQ",
    detail:
      "Checks the call against the signed plan and the policy, then returns allow, hold for a manager, or block.",
    accent: true,
  },
  {
    icon: Database,
    name: "Hotel MCP server",
    detail: "Seventeen FastMCP tools over Postgres. It runs business logic only; permission is never its job.",
  },
];

/**
 * Scroll-driven walk through the six hops. The section is tall and its content is sticky: as the
 * reader scrolls, an orange line fills and each stage lights in order (storytelling: the request
 * travels the pipeline). Under reduced motion, or on small screens, every stage is listed statically.
 */
export function Pipeline() {
  const ref = useRef<HTMLElement>(null);
  const reduce = useReducedMotion();
  const [active, setActive] = useState(0);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const progress = useSpring(scrollYProgress, { stiffness: 120, damping: 24, mass: 0.4 });
  const lineScale = useTransform(progress, [0.04, 0.92], [0, 1], { clamp: true });

  useMotionValueEvent(scrollYProgress, "change", (v) => {
    const next = Math.min(STAGES.length - 1, Math.max(0, Math.floor(v * STAGES.length * 1.02)));
    if (next !== active) setActive(next);
  });

  const stage = STAGES[active];

  return (
    <section ref={ref} id="how" className="relative scroll-mt-20 md:h-[320vh]">
      <div className="border-y border-line bg-panel/40 md:sticky md:top-16 md:flex md:h-[calc(100dvh-4rem)] md:items-center">
        <div className="mx-auto w-full max-w-[1400px] px-4 py-24 md:px-8 md:py-0">
          <h2 className="max-w-[20ch] text-4xl font-medium leading-[1.05] tracking-[-0.03em] md:text-5xl">
            Six hops from a sentence to a refund.
          </h2>

          {/* Desktop: sticky, scroll-driven rail. */}
          <div className="relative mt-16 hidden md:block">
            <div className="absolute left-7 right-[calc(100%/6-1.75rem)] top-7 h-px bg-line-strong" />
            <motion.div
              className="absolute left-7 right-[calc(100%/6-1.75rem)] top-7 h-px origin-left bg-accent shadow-[0_0_12px_rgb(242_85_29/0.6)]"
              style={{ scaleX: reduce ? 1 : lineScale }}
            />
            <ol className="relative grid grid-cols-6">
              {STAGES.map((s, i) => {
                const Icon = s.icon;
                const done = i < active;
                const isActive = i === active;
                return (
                  <li key={s.name} className="flex flex-col items-start gap-4">
                    <span
                      className={`relative flex h-14 w-14 items-center justify-center rounded-full border transition-all duration-500 ${
                        isActive
                          ? "scale-110 border-accent bg-accent text-ink shadow-[0_0_32px_rgb(242_85_29/0.45)]"
                          : done
                            ? "border-accent/70 bg-ink text-accent"
                            : "border-line-strong bg-ink text-dim"
                      }`}
                    >
                      <Icon size={22} weight={isActive ? "fill" : "duotone"} />
                    </span>
                    <span
                      className={`text-sm transition-colors duration-500 ${
                        isActive ? "text-text" : done ? "text-muted" : "text-dim"
                      }`}
                    >
                      {s.name}
                    </span>
                  </li>
                );
              })}
            </ol>

            <div className="mt-14 min-h-[7.5rem]">
              <motion.p
                key={stage.name}
                initial={reduce ? false : { opacity: 0, y: 10, filter: "blur(4px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
                className="max-w-[52ch] text-2xl leading-snug tracking-[-0.015em] text-text md:text-3xl"
              >
                <span className={stage.accent ? "text-accent" : "text-muted"}>{stage.name}.</span>{" "}
                {stage.detail}
              </motion.p>
            </div>
          </div>

          {/* Mobile: the same six hops as a vertical, readable list. */}
          <ol className="relative mt-12 space-y-8 border-l border-accent/40 pl-6 md:hidden">
            {STAGES.map((s) => {
              const Icon = s.icon;
              return (
                <li key={s.name} className="relative">
                  <span className="absolute -left-[2.15rem] top-0 flex h-7 w-7 items-center justify-center rounded-full border border-accent/60 bg-ink text-accent">
                    <Icon size={14} weight="duotone" />
                  </span>
                  <h3 className={`text-base font-medium ${s.accent ? "text-accent" : "text-text"}`}>{s.name}</h3>
                  <p className="mt-1 text-[15px] leading-relaxed text-muted">{s.detail}</p>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </section>
  );
}
