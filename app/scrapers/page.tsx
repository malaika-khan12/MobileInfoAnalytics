import type { Metadata } from "next";
import { ScraperWorkspace } from "../../frontend/scrapers";

export const metadata: Metadata = {
  title: "Scrapers",
  description: "Configure and monitor governed mobile-data collection jobs.",
};

export default function ScrapersPage() {
  return <ScraperWorkspace sourceKey="mymobile" />;
}
