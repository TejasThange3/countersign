import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  // Link previews (WhatsApp, X, Slack) need absolute image URLs; the images are
  // app/opengraph-image.jpg and app/twitter-image.jpg.
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://countersign-aimcp.vercel.app"),
  title: "Countersign | A voice agent that can't be talked into anything",
  description:
    "A real-time voice front desk where every refund, booking and data request is checked by ArmorIQ before it runs.",
  openGraph: {
    title: "Countersign: a voice agent that can't be talked into anything",
    description: "Callers can persuade the model. They can't move money. ArmorIQ checks every action before it runs.",
    type: "website",
    siteName: "Countersign",
  },
  twitter: {
    card: "summary_large_image",
    title: "Countersign: a voice agent that can't be talked into anything",
    description: "Callers can persuade the model. They can't move money. ArmorIQ checks every action before it runs.",
  },
};

export const viewport: Viewport = {
  themeColor: "#0a0a0a",
  colorScheme: "dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
      <body className="grain min-h-[100dvh] bg-ink text-text">{children}</body>
    </html>
  );
}
