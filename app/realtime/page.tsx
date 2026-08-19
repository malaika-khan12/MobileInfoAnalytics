import type { Metadata } from "next";
import { RealtimeAnalytics } from "../../frontend/realtime";

export const metadata: Metadata = {
  title: "Real-time analytics",
  description: "Live market events, source health, anomalies, and operational telemetry.",
};

export default function RealtimePage() {
  return <RealtimeAnalytics />;
}
