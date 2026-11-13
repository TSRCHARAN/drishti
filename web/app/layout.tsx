import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import ThemeToggle from "./theme-toggle";

export const metadata: Metadata = {
  title: "Veekshana",
  description: "Open-source observability for AI agents",
};

// Applies the saved theme before first paint so there is no flash.
const themeInit = `(function(){try{var t=localStorage.getItem("veekshana-theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t);}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body>
        <nav className="nav">
          <Link href="/" className="brand">🔭 Veekshana</Link>
          <Link href="/" className="link">Dashboard</Link>
          <Link href="/traces" className="link">Traces</Link>
          <div className="spacer" />
          <ThemeToggle />
          <a
            className="link faint"
            href="https://github.com/TSRCHARAN/veekshana"
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
