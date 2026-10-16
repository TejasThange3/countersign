"use client";

import { motion, useReducedMotion } from "motion/react";
import { ArrowRight, LockSimple, UserCircleDashed, UserCircleCheck } from "@phosphor-icons/react";
import { Frame } from "@/components/frame";
import { Stamp } from "@/components/stamp";
import run from "@/data/live-run.json";

const held = run.cases.find((c) => c.reason === "approved");

const FLOW = [
  { kind: "hold" as const, label: "hold", text: "Agent proposes issue_refund, $40" },
  { kind: "hold" as const, label: "waiting", text: "A manager reviews the signed plan" },
  { kind: "allow" as const, label: "approved", text: "The refund runs exactly once" },
];

export function Principles() {
  const reduce = useReducedMotion();

  return (
    <section className="mx-auto max-w-[1400px] px-4 pb-28 md:px-8 md:pb-36">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {/* Core rule, with the real hold lifecycle drawn as a filling track. */}
        <Frame spotlight as="article" className="overflow-hidden p-8 md:col-span-2 md:row-span-2 md:p-12">
          <div className="pointer-events-none absolute -right-32 -top-32 h-[30rem] w-[30rem] rounded-full bg-[radial-gradient(circle,rgb(242_85_29/0.18),transparent_65%)]" />
          <div className="relative max-w-[34ch]">
            <h3 className="text-3xl font-medium leading-[1.08] tracking-[-0.025em] md:text-[2.6rem]">
              Words don&apos;t move money.
            </h3>
            <p className="mt-4 text-[17px] leading-relaxed text-muted">
              Every refund, credit or fee waiver waits for a manager to countersign it in ArmorIQ.
              The agent keeps talking to the caller while it waits.
            </p>
          </div>

          <div className="relative mt-16">
            <div className="absolute left-0 right-0 top-[11px] hidden h-px bg-line-strong sm:block" />
            <motion.div
              className="absolute left-0 right-0 top-[11px] hidden h-px origin-left bg-accent sm:block"
              initial={reduce ? false : { scaleX: 0 }}
              whileInView={{ scaleX: 1 }}
              viewport={{ once: true, amount: 0.6 }}
              transition={{ duration: 1.6, ease: [0.16, 1, 0.3, 1] }}
            />
            <ol className="relative grid grid-cols-1 gap-8 sm:grid-cols-3 sm:gap-6">
              {FLOW.map((step, i) => (
                <li key={step.label}>
                  <span className="relative inline-flex h-[23px] items-center bg-panel pr-3">
                    <Stamp kind={step.kind} label={step.label} delay={0.35 + i * 0.45} />
                  </span>
                  <p className="mt-4 text-[15px] leading-snug text-text">{step.text}</p>
                </li>
              ))}
            </ol>
            {held && (
              <p className="mt-10 font-mono text-[12px] text-dim">
                delegation {held.delegation_id?.slice(0, 8)} / plan {held.plan_id?.slice(0, 8)}
              </p>
            )}
          </div>
        </Frame>

        {/* Identity: the only way from stranger to guest is verification inside the bridge. */}
        <Frame spotlight as="article" className="p-8">
          <div className="flex items-center gap-3 font-mono text-[12px]">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-2.5 py-1 text-muted">
              <UserCircleDashed size={14} /> stranger
            </span>
            <ArrowRight size={14} className="text-dim" />
            <motion.span
              initial={reduce ? false : { opacity: 0, x: -6 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ delay: 0.5, duration: 0.5 }}
              className="inline-flex items-center gap-1.5 rounded-full border border-accent/50 bg-accent-soft px-2.5 py-1 text-accent"
            >
              <UserCircleCheck size={14} weight="fill" /> guest
            </motion.span>
          </div>
          <h3 className="mt-8 text-xl font-medium tracking-[-0.02em]">Identity comes from verification.</h3>
          <p className="mt-3 text-[15px] leading-relaxed text-muted">
            &ldquo;I&apos;m the night manager&rdquo; changes nothing. Only a booking reference and
            surname turn a stranger into a guest, and only the bridge can make that switch.
          </p>
        </Frame>

        {/* Signed: a real plan id, shown the way an engineer would read it. */}
        <Frame spotlight as="article" className="overflow-hidden p-8">
          <pre className="relative overflow-hidden rounded-lg border border-line bg-ink/70 p-4 font-mono text-[11.5px] leading-relaxed text-muted">
            <span className="text-dim">{"{"}</span>
            {"\n"}  <span className="text-text">&quot;plan&quot;</span>: &quot;{held?.plan_id?.slice(0, 18)}…&quot;,
            {"\n"}  <span className="text-text">&quot;policy&quot;</span>: &quot;{held?.policy}&quot;,
            {"\n"}  <span className="text-text">&quot;mode&quot;</span>: &quot;{run.armoriq_mode}&quot;
            {"\n"}<span className="text-dim">{"}"}</span>
            <span className="pointer-events-none absolute inset-x-0 h-8 animate-[scan_3.2s_ease-in-out_infinite] bg-gradient-to-b from-transparent via-accent/15 to-transparent" />
          </pre>
          <h3 className="mt-7 flex items-center gap-2 text-xl font-medium tracking-[-0.02em]">
            <LockSimple size={18} className="text-accent" /> Every decision is signed.
          </h3>
          <p className="mt-3 text-[15px] leading-relaxed text-muted">
            Each call declares its tools as a signed intent plan. Allowed, held and blocked actions all
            land in ArmorIQ&apos;s audit trail.
          </p>
        </Frame>
      </div>
    </section>
  );
}
