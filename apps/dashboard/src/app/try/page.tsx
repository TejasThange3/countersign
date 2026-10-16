import type { Metadata } from "next";
import { Nav } from "@/components/nav";
import { TryConsole } from "@/components/try/try-console";

export const metadata: Metadata = {
  title: "Try Countersign | Call the front desk",
  description:
    "Talk to a hotel front desk agent whose every action is checked by ArmorIQ. Try to talk it into a refund.",
};

export default function TryPage() {
  return (
    <>
      <Nav />
      <main className="mx-auto max-w-[1400px] px-4 py-8 md:px-8 md:py-10">
        <div className="mb-8 max-w-[70ch]">
          <h1 className="text-3xl font-medium tracking-[-0.03em] md:text-4xl">Call the front desk.</h1>
          <p className="mt-3 text-[15px] leading-relaxed text-muted">
            A live agent, a real hotel database and ArmorIQ checking every action. Follow the steps, or try
            to talk it into something it shouldn&apos;t do.
          </p>
        </div>
        <TryConsole />
      </main>
    </>
  );
}
