import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sentriq | Disaster Intelligence",
  description: "A terrain-based dam-break simulation workspace for SIH 26161. Explore scenarios, inundation, model comparisons, and HADR exposure.",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
