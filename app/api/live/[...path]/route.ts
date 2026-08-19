import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

function controlBase(): string {
  let raw = (process.env.CONTROL_API_URL || "http://127.0.0.1:5050").trim();
  raw = raw.replace(/^['"]|['"]$/g, "");
  // Be forgiving of the common local .env typo `http://127.0.0.1:5050:`.
  if (/^https?:\/\/[^/]+:\d+:$/.test(raw)) raw = raw.slice(0, -1);
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("CONTROL_API_URL is invalid. Use http://127.0.0.1:5050 for local Windows development.");
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error("CONTROL_API_URL must use http:// or https://.");
  }
  return parsed.href.replace(/\/$/, "");
}

function isCrossSiteWrite(request: NextRequest): boolean {
  if (request.method === "GET" || request.method === "HEAD") return false;
  return request.headers.get("sec-fetch-site") === "cross-site";
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (isCrossSiteWrite(request)) {
    return NextResponse.json({ ok: false, error: "Cross-site write request rejected." }, { status: 403 });
  }

  try {
    const { path } = await context.params;
    const suffix = path.map(encodeURIComponent).join("/");
    const upstream = new URL(`${controlBase()}/api/${suffix}`);
    request.nextUrl.searchParams.forEach((value, key) => upstream.searchParams.append(key, value));

    const headers = new Headers({ Accept: "application/json" });
    const cookie = request.headers.get("cookie");
    if (cookie) headers.set("Cookie", cookie);
    if (request.method !== "GET" && request.method !== "HEAD") headers.set("Content-Type", "application/json");

    const body = request.method === "GET" || request.method === "HEAD" ? undefined : await request.text();
    const response = await fetch(upstream, { method: request.method, headers, body, cache: "no-store" });
    const responseBody = await response.text();
    const outgoing = new Headers({
      "content-type": response.headers.get("content-type") || "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    });
    const setCookie = response.headers.get("set-cookie");
    if (setCookie) outgoing.set("set-cookie", setCookie.replace(/Path=\//i, "Path=/api/live"));
    return new NextResponse(responseBody, { status: response.status, headers: outgoing });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: `Control API unavailable: ${error instanceof Error ? error.message : String(error)}` },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
