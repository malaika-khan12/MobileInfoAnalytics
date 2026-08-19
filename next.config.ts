import type { NextConfig } from "next";

const isDevelopment = process.env.NODE_ENV !== "production";
const scriptPolicy = `script-src 'self' 'unsafe-inline'${isDevelopment ? " 'unsafe-eval'" : ""}`;
const connectPolicy = `connect-src 'self'${isDevelopment ? " ws: wss:" : ""}`;

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Content-Security-Policy", value: `default-src 'self'; ${scriptPolicy}; style-src 'self' 'unsafe-inline'; img-src 'self' data:; ${connectPolicy}; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'` },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
