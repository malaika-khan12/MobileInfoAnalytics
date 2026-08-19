import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ScraperWorkspace } from "../../../frontend/scrapers";
import type { SourceKey } from "../../../frontend/types";

const SOURCE_KEYS: SourceKey[] = ["mymobile", "daraz", "gsmarena", "mega", "whatamobile", "whatmobile"];

export function generateStaticParams() {
  return SOURCE_KEYS.map((source) => ({ source }));
}

export async function generateMetadata({ params }: { params: Promise<{ source: string }> }): Promise<Metadata> {
  const { source } = await params;
  return { title: `${source} scraper` };
}

export default async function SourceScraperPage({ params }: { params: Promise<{ source: string }> }) {
  const { source } = await params;
  if (!SOURCE_KEYS.includes(source as SourceKey)) notFound();
  return <ScraperWorkspace sourceKey={source as SourceKey} />;
}
