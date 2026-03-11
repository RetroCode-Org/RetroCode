import { ThemeProvider } from "@/components/ThemeProvider";
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://retrocode.dev"),
  title: {
    default: "RetroCode -- Agent Augmentation from Session Traces",
    template: "%s | RetroCode",
  },
  description:
    "Turn AI coding agent session traces into auto-updating project playbooks. RetroCode reads Claude Code, Cursor, and Codex traces to generate actionable rules, statistical hypotheses, and blast radius insights.",
  icons: {
    icon: "/favicon.svg",
  },
  openGraph: {
    title: "RetroCode -- Agent Augmentation from Session Traces",
    description:
      "Turn AI coding agent session traces into auto-updating project playbooks and statistical insights.",
    siteName: "RetroCode",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning className="font-satoshi">
      <head>
        <link
          href="https://api.fontshare.com/v2/css?f[]=satoshi@300,400,500,700,900&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased">
        <ThemeProvider>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
