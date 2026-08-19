import Link from "next/link";
import { AppShell } from "../frontend/app-shell";
import { Icon } from "../frontend/icons";

export default function NotFound() {
  return (
    <AppShell>
      <div className="page-container">
        <section className="panel" style={{ maxWidth: 620, margin: "10vh auto", padding: 40, textAlign: "center" }}>
          <span className="insight-icon" style={{ margin: "0 auto 18px" }}><Icon name="search" /></span>
          <p className="eyebrow">404 · Not found</p>
          <h1 style={{ margin: 0, fontSize: 32 }}>This workspace does not exist.</h1>
          <p style={{ color: "var(--muted)", margin: "10px auto 22px", maxWidth: 430 }}>The page may have moved, or the scraper source is not configured in this frontend.</p>
          <Link className="button button-primary" href="/dashboard"><Icon name="grid" />Return to dashboard</Link>
        </section>
      </div>
    </AppShell>
  );
}
