import type { Metadata } from "next";
import { DatabaseView } from "../../frontend/database-view";

export const metadata: Metadata = {
  title: "Database view",
  description: "A read-only explorer for normalized mobile-market records.",
};

export default function DatabasePage() {
  return <DatabaseView />;
}
