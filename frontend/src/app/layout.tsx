import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HeatShield AI | Autonomous Heat Intelligence",
  description:
    "Enterprise OSHA heat hazard compliance & monitoring agent — hyperlocal street-level microclimate intelligence fused with a 5-tier resilient reasoning cascade to protect outdoor worksites in real time.",
  icons: {
    icon:
      "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%2306b6d4' stroke='%230891b2' stroke-width='1.5'><path d='M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'/><circle cx='12' cy='12' r='3' fill='%2322d3ee'/></svg>",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="font-body min-h-screen antialiased">{children}</body>
    </html>
  );
}
