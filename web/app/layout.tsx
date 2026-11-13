import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Drishti",
  description: "Open-source observability for AI agents",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav className="nav">
          <Link href="/" className="brand">🔭 Drishti</Link>
          <Link href="/" className="link">Dashboard</Link>
          <Link href="/traces" className="link">Traces</Link>
          <div className="spacer" />
          <a
            className="link faint"
            href="https://github.com/TSRCHARAN/drishti"
            target="_blank"
            rel="noreferrer"
          >
            GitHub
          </a>
        </nav>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
