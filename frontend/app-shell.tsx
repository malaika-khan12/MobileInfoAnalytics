/* The supplied brand PNG is intentionally rendered at its native transparent size. */
/* eslint-disable @next/next/no-img-element */
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Icon } from "./icons";
import type { IconName } from "./types";

const NAV_ITEMS: { href: string; label: string; icon: IconName; matcher: string }[] = [
  { href: "/scrapers", label: "Scrapers", icon: "globe", matcher: "/scrapers" },
  { href: "/admin", label: "Admin panel", icon: "terminal", matcher: "/admin" },
  { href: "/database", label: "Database view", icon: "database", matcher: "/database" },
  { href: "/dashboard", label: "Dashboard", icon: "grid", matcher: "/dashboard" },
  { href: "/realtime", label: "Real-time analytics", icon: "activity", matcher: "/realtime" },
];

type AppShellProps = {
  children: React.ReactNode;
  footer?: boolean;
};

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const stored = window.localStorage.getItem("mobile-analytics-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const next = stored === "dark" || (!stored && prefersDark) ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    const timer = window.setTimeout(() => setTheme(next), 0);
    return () => window.clearTimeout(timer);
  }, []);

  function toggleTheme() {
    const next = theme === "light" ? "dark" : "light";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    window.localStorage.setItem("mobile-analytics-theme", next);
  }

  return (
    <button className="icon-button" type="button" onClick={toggleTheme} aria-label={`Switch to ${theme === "light" ? "dark" : "light"} theme`} title="Change theme">
      <Icon name={theme === "light" ? "moon" : "sun"} />
    </button>
  );
}

function CommandMenu({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState("");
  const matches = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return NAV_ITEMS;
    return NAV_ITEMS.filter((item) => item.label.toLowerCase().includes(normalized));
  }, [query]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="modal-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="command-menu" role="dialog" aria-modal="true" aria-label="Quick navigation">
        <div className="command-search">
          <Icon name="search" />
          <input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Jump to a workspace…" aria-label="Search workspaces" />
          <kbd>ESC</kbd>
        </div>
        <div className="command-results">
          <p className="command-label">Workspaces</p>
          {matches.map((item) => (
            <Link className="command-item" href={item.href} key={item.href} onClick={onClose}>
              <span className="command-item-icon"><Icon name={item.icon} /></span>
              <span>{item.label}</span>
              <Icon name="arrow-right" size={16} />
            </Link>
          ))}
          {matches.length === 0 && <div className="command-empty">No workspace matches “{query}”.</div>}
        </div>
      </div>
    </div>
  );
}

function Footer() {
  return (
    <footer className="site-footer">
      <div className="footer-main">
        <div className="footer-brand">
          <img src="/brand-mark.png" alt="" />
          <div>
            <strong>Mobile Analytics</strong>
            <p>A control plane for reliable mobile-market data.</p>
          </div>
        </div>
        <div className="footer-meta">
          <span>Live-data frontend</span>
          <span>Asia/Karachi · PKT</span>
          <span>Production control plane</span>
        </div>
      </div>
      <div className="footer-bottom">
        <span>Built for governed collection, normalization, and analysis.</span>
        <nav aria-label="Footer navigation">
          <Link href="/database">Data catalogue</Link>
          <Link href="/admin">Operations</Link>
          <Link href="/realtime">Live status</Link>
        </nav>
      </div>
    </footer>
  );
}

export function AppShell({ children, footer = false }: AppShellProps) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((current) => !current);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const isActive = (matcher: string) => {
    if (matcher === "/dashboard" && pathname === "/") return true;
    return pathname === matcher || pathname.startsWith(`${matcher}/`);
  };

  return (
    <div className="app-frame">
      <header className="topbar">
        <div className="topbar-inner">
          <Link className="product-brand" href="/dashboard" aria-label="Mobile Analytics dashboard">
            <span className="brand-mark"><img src="/brand-mark.png" alt="" /></span>
            <span className="brand-copy"><strong>Mobile Analytics</strong><small>Intelligence platform</small></span>
          </Link>

          <nav className={`primary-nav ${menuOpen ? "is-open" : ""}`} aria-label="Primary navigation">
            {NAV_ITEMS.map((item) => (
              <Link className={isActive(item.matcher) ? "active" : ""} href={item.href} key={item.href} aria-current={isActive(item.matcher) ? "page" : undefined} onClick={() => setMenuOpen(false)}>
                <Icon name={item.icon} />
                <span>{item.label}</span>
              </Link>
            ))}
          </nav>

          <div className="topbar-actions">
            <button className="quick-search" type="button" onClick={() => setCommandOpen(true)} aria-label="Open quick navigation">
              <Icon name="search" />
              <span>Quick find</span>
              <kbd>⌘ K</kbd>
            </button>
            <ThemeToggle />
            <Link className="icon-button notification-button" href="/realtime" aria-label="Open live status" title="Live status">
              <Icon name="bell" />
            </Link>
            <Link className="avatar-button" href="/admin" aria-label="Open operations console" title="Operations">
              <span>OP</span>
            </Link>
            <button className="icon-button mobile-menu-button" type="button" onClick={() => setMenuOpen((current) => !current)} aria-label="Toggle navigation" aria-expanded={menuOpen}>
              <Icon name={menuOpen ? "x" : "menu"} />
            </button>
          </div>
        </div>
      </header>

      <main className="workspace">{children}</main>
      {footer && <Footer />}
      {commandOpen && <CommandMenu onClose={() => setCommandOpen(false)} />}
    </div>
  );
}

export function Breadcrumbs({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      {items.map((item, index) => (
        <span key={`${item.label}-${index}`}>
          {item.href ? <Link href={item.href}>{item.label}</Link> : <span aria-current="page">{item.label}</span>}
          {index < items.length - 1 && <Icon name="chevron-right" size={14} />}
        </span>
      ))}
    </nav>
  );
}

export function PageHeading({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description: string; actions?: React.ReactNode }) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase().replaceAll(" ", "-");
  return <span className={`status-badge status-${normalized}`}><i />{status}</span>;
}
