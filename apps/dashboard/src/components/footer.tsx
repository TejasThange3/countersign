import { DotWordmark } from "@/components/dot-wordmark";
import { REPO_URL } from "@/lib/site";

export function Footer() {
  return (
    <footer className="relative overflow-hidden border-t border-line">
      <div className="mx-auto max-w-[1400px] px-4 pt-24 md:px-8">
        <div className="flex flex-col gap-10 md:flex-row md:items-end md:justify-between">
          <p className="max-w-[40ch] text-2xl leading-snug tracking-[-0.02em] md:text-3xl">
            The model can want anything.{" "}
            <span className="text-accent">It can only do what&apos;s countersigned.</span>
          </p>
          <ul className="flex gap-8 text-sm text-muted">
            <li>
              <a className="transition-colors hover:text-text" href={REPO_URL}>
                Source
              </a>
            </li>
            <li>
              <a className="transition-colors hover:text-text" href="https://docs.armoriq.ai">
                ArmorIQ docs
              </a>
            </li>
            <li>
              <a className="transition-colors hover:text-text" href="#top">
                Back to top
              </a>
            </li>
          </ul>
        </div>
      </div>

      <div className="mt-14 px-2 pb-6 md:px-4 md:pb-10">
        <DotWordmark />
      </div>
    </footer>
  );
}
