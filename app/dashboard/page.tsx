import type { Metadata } from "next";
import { Dashboard } from "../../frontend/dashboard";

export const metadata: Metadata = {
  title: "Dashboard",
  description: "Mobile market catalogue, pricing, coverage, and quality analytics.",
};

export default function DashboardPage() {
  return <Dashboard />;
}
