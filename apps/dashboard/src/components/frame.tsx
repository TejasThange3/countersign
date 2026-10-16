"use client";

import { useRef, type ReactNode, type PointerEvent } from "react";

/**
 * The page's one surface material: a hairline frame with corner ticks (an engineering-drawing
 * cue), a faint top light edge, and an optional cursor-following orange edge light. Pointer
 * position is written to CSS variables directly, so moving the mouse never re-renders React.
 */
export function Frame({
  children,
  className = "",
  spotlight = false,
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  spotlight?: boolean;
  as?: "div" | "article" | "section" | "li";
}) {
  const ref = useRef<HTMLElement>(null);

  const onMove = (e: PointerEvent<HTMLElement>) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - r.left}px`);
    el.style.setProperty("--my", `${e.clientY - r.top}px`);
  };

  return (
    <Tag
      // biome-ignore lint: polymorphic ref
      ref={ref as never}
      onPointerMove={spotlight ? onMove : undefined}
      className={`frame group/frame relative isolate rounded-xl border border-line bg-panel ${className}`}
    >
      {spotlight && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -inset-px -z-10 rounded-[inherit] opacity-0 transition-opacity duration-300 group-hover/frame:opacity-100"
          style={{
            background:
              "radial-gradient(420px circle at var(--mx, 50%) var(--my, 50%), rgb(242 85 29 / 0.10), transparent 60%)",
          }}
        />
      )}
      {spotlight && <span aria-hidden="true" className="frame-edge" />}
      <span aria-hidden="true" className="tick tick-tl" />
      <span aria-hidden="true" className="tick tick-tr" />
      <span aria-hidden="true" className="tick tick-bl" />
      <span aria-hidden="true" className="tick tick-br" />
      {children}
    </Tag>
  );
}
