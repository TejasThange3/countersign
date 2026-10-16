"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { PaperPlaneRight } from "@phosphor-icons/react";
import type { CallStatus, Line } from "@/lib/use-agent-call";

const PLACEHOLDER: Record<CallStatus, string> = {
  idle: "Say something to the front desk…",
  connecting: "Connecting to the front desk…",
  thinking: "The agent is replying…",
  held: "Waiting for the manager's decision…",
  deciding: "Sending your decision to ArmorIQ…",
  ready: "Type your next line…",
  error: "Try again…",
};

export function Transcript({
  lines,
  status,
  onSend,
}: {
  lines: Line[];
  status: CallStatus;
  onSend: (text: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const busy =
    status === "thinking" || status === "held" || status === "deciding" || status === "connecting";

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "end" });
  }, [lines.length, status, reduce]);

  const submit = () => {
    if (busy || !draft.trim()) return;
    onSend(draft);
    setDraft("");
  };

  return (
    <div className="flex h-full min-h-[24rem] flex-col lg:min-h-[28rem]">
      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-6 md:px-7" aria-live="polite">
        {lines.length === 0 && (
          <p className="mx-auto mt-16 max-w-[34ch] text-center text-[15px] leading-relaxed text-dim">
            You&apos;re calling The Larkspur&apos;s front desk. Pick a step from the list, or type anything.
          </p>
        )}
        <AnimatePresence initial={false}>
          {lines.map((line) => (
            <motion.div
              key={line.id}
              initial={reduce ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
              className={
                line.who === "caller" ? "flex justify-end" : line.who === "note" ? "flex justify-center" : "flex"
              }
            >
              {line.who === "note" ? (
                <span className="rounded-full border border-accent/30 bg-accent/10 px-3 py-1 font-mono text-[11px] uppercase tracking-[0.12em] text-accent">
                  {line.text}
                </span>
              ) : (
                <p
                  className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed ${
                    line.who === "caller"
                      ? "rounded-br-md bg-accent text-ink"
                      : "rounded-bl-md border border-line bg-panel-2 text-text"
                  }`}
                >
                  {line.text}
                </p>
              )}
            </motion.div>
          ))}
        </AnimatePresence>
        {status === "thinking" && (
          <div className="flex gap-1 pl-2" aria-label="The agent is replying">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted"
                style={{ animationDelay: `${i * 160}ms` }}
              />
            ))}
          </div>
        )}
        <div ref={end} />
      </div>

      <form
        className="flex items-center gap-2 border-t border-line p-3"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label htmlFor="caller-line" className="sr-only">
          Your message
        </label>
        <input
          id="caller-line"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={PLACEHOLDER[status]}
          disabled={busy}
          maxLength={400}
          autoComplete="off"
          className="h-11 flex-1 rounded-xl border border-line bg-ink px-4 text-[15px] text-text outline-none transition-colors placeholder:text-dim focus:border-accent/60 disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={busy || !draft.trim()}
          aria-label="Send"
          className="inline-flex h-11 w-11 cursor-pointer items-center justify-center rounded-xl bg-accent text-ink transition-[background-color,transform] duration-200 hover:bg-accent-hover active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-40"
        >
          <PaperPlaneRight size={18} weight="fill" />
        </button>
      </form>
    </div>
  );
}
