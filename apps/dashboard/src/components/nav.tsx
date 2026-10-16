import Link from "next/link";
import { ArrowRight, GithubLogo, SealCheck } from "@phosphor-icons/react/dist/ssr";
import { CtaButton } from "@/components/cta-button";
import { REPO_URL } from "@/lib/site";

// Root-relative so they also work from /try.
const LINKS = [
  { href: "/#live", label: "Live call" },
  { href: "/#how", label: "How it works" },
  { href: "/#policy", label: "Policy" },
  { href: "/#proof", label: "Proof" },
];

export function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-ink/80 backdrop-blur-md">
      <nav className="mx-auto flex h-16 max-w-[1400px] items-center justify-between px-4 md:px-8">
        <Link href="/" className="flex items-center gap-2.5" aria-label="Countersign home">
          <SealCheck size={22} weight="duotone" className="text-accent" />
          <span className="text-[15px] font-medium tracking-tight">Countersign</span>
        </Link>
        <ul className="hidden items-center gap-8 text-sm text-muted md:flex">
          {LINKS.map((l) => (
            <li key={l.href}>
              <Link href={l.href} className="transition-colors duration-200 hover:text-text">
                {l.label}
              </Link>
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-1">
          <CtaButton
            href={REPO_URL}
            variant="ghost"
            size="sm"
            label="Source on GitHub"
            icon={<GithubLogo size={15} weight="bold" />}
          >
            <span className="hidden sm:inline">Source</span>
          </CtaButton>
          <CtaButton href="/try" size="sm" trailing={<ArrowRight size={14} weight="bold" />}>
            Try it
          </CtaButton>
        </div>
      </nav>
    </header>
  );
}
