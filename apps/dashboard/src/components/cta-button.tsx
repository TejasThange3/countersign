import Link from "next/link";
import type { ReactNode } from "react";

/**
 * The site's call-to-action: a squared button framed by four corner brackets that snap in to
 * hug it on hover (the same corner ticks as the `.frame` panels), plus a light sweep across
 * the primary face. After the corner-button idea in Vengeance UI; styles live in globals.css
 * (`.cta`), so the server-rendered nav needs no client JavaScript.
 */
export function CtaButton({
  href,
  children,
  icon,
  trailing,
  variant = "primary",
  size = "md",
  label,
}: {
  href: string;
  children: ReactNode;
  /** Shown before the label (e.g. the GitHub mark). */
  icon?: ReactNode;
  /** Shown after the label; nudges forward on hover (e.g. an arrow). */
  trailing?: ReactNode;
  variant?: "primary" | "ghost";
  size?: "md" | "sm";
  /** Accessible name when the visible label is hidden on small screens. */
  label?: string;
}) {
  const external = /^https?:/.test(href);
  const className = `cta cta-${variant} cta-${size}`;
  const inner = (
    <>
      <span aria-hidden className="cta-corner cta-tl" />
      <span aria-hidden className="cta-corner cta-tr" />
      <span aria-hidden className="cta-corner cta-bl" />
      <span aria-hidden className="cta-corner cta-br" />
      <span className="cta-face">
        {icon}
        {children}
        {trailing && <span className="cta-trailing">{trailing}</span>}
      </span>
    </>
  );
  return external ? (
    <a href={href} className={className} aria-label={label} target="_blank" rel="noreferrer">
      {inner}
    </a>
  ) : (
    <Link href={href} className={className} aria-label={label}>
      {inner}
    </Link>
  );
}
