import type { Metadata } from "next";
import { AdminPanel } from "../../frontend/admin";

export const metadata: Metadata = {
  title: "Admin panel",
  description: "Authenticated, allowlisted scraper, ETL, validation, preflight, and database synchronization operations.",
};

export default function AdminPage() {
  return <AdminPanel />;
}
