import Link from "next/link";
import { ArrowRight, GithubLogo, SealCheck } from "@phosphor-icons/react/dist/ssr";
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
        <div className="flex items-center gap-2">
          <a
            href={REPO_URL}
            aria-label="Source on GitHub"
            className="inline-flex items-center gap-2 rounded-full border border-line-strong px-3 py-2 text-sm text-text transition-[background-color,transform] duration-200 hover:bg-panel-2 active:scale-[0.98] sm:px-4"
          >
            <GithubLogo size={16} weight="bold" />
            <span className="hidden sm:inline">Source</span>
          </a>
          <Link
            href="/try"
            className="group inline-flex items-center gap-1.5 rounded-full bg-accent px-4 py-2 text-sm font-medium text-ink transition-[background-color,transform] duration-200 hover:bg-accent-hover active:scale-[0.98]"
          >
            Try it
            <ArrowRight
              size={14}
              weight="bold"
              className="transition-transform duration-200 group-hover:translate-x-0.5"
            />
          </Link>
        </div>
      </nav>
    </header>
  );
}
