import { ArrowRight, GithubLogo } from "@phosphor-icons/react/dist/ssr";
import { CtaButton } from "@/components/cta-button";
import { Guilloche } from "@/components/guilloche";
import { Reveal } from "@/components/reveal";
import { REPO_URL } from "@/lib/site";

export function Hero() {
  return (
    <section id="top" className="px-3 pt-3 md:px-4">
      <div className="relative isolate overflow-hidden rounded-[24px] border border-line bg-panel">
        <Guilloche className="absolute inset-0 -z-10 h-full w-full" />
        {/* Vignette keeps the copy side calm and readable over the engraving. */}
        <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_70%_50%,transparent_0%,transparent_45%,rgb(17_17_16/0.7)_85%)]" />
        <div className="pointer-events-none absolute inset-y-0 left-0 -z-10 h-1/2 w-full bg-gradient-to-b from-panel via-panel/80 to-transparent md:h-full md:w-[55%] md:bg-gradient-to-r" />

        <div className="mx-auto flex min-h-[calc(100dvh-5.5rem)] max-w-[1400px] flex-col justify-start px-6 pb-20 pt-16 md:justify-center md:px-14 md:py-20">
          <Reveal>
            <h1 className="max-w-[16ch] text-[2.6rem] font-medium leading-[1.02] tracking-[-0.035em] md:text-6xl lg:text-7xl">
              A voice agent that can&apos;t be talked into anything.
            </h1>
          </Reveal>
          <Reveal delay={0.08}>
            <p className="mt-6 max-w-[46ch] text-lg leading-relaxed text-muted">
              Callers can persuade the model. They can&apos;t move money. ArmorIQ checks every
              action before it runs.
            </p>
          </Reveal>
          <Reveal delay={0.16}>
            <div className="mt-10 flex flex-wrap items-center gap-2">
              <CtaButton href="/try" trailing={<ArrowRight size={16} weight="bold" />}>
                Try to talk it into a refund
              </CtaButton>
              <CtaButton href={REPO_URL} variant="ghost" icon={<GithubLogo size={16} weight="bold" />}>
                Read the code
              </CtaButton>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
