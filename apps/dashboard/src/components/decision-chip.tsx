export type DecisionKind = "allow" | "hold" | "block";

const STYLE: Record<DecisionKind, string> = {
  allow: "text-allow border-allow/30 bg-allow/10",
  hold: "text-hold border-hold/30 bg-hold/10",
  block: "text-block border-block/30 bg-block/10",
};

export function DecisionChip({ kind, label }: { kind: DecisionKind; label?: string }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-full border px-2.5 py-0.5 font-mono text-[11px] font-medium uppercase tracking-wider ${STYLE[kind]}`}
    >
      {label ?? kind}
    </span>
  );
}
