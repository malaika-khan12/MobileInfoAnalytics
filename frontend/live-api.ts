"use client";

export type JsonRecord = Record<string, unknown>;

export async function liveApi<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/live/${path.replace(/^\//, "")}`, {
    cache: "no-store",
    credentials: "same-origin",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = { ok: false, error: `Invalid JSON response (${response.status})` };
  }
  if (!response.ok || (payload && typeof payload === "object" && "ok" in payload && (payload as { ok?: boolean }).ok === false)) {
    const message = payload && typeof payload === "object" && "error" in payload ? String((payload as { error?: unknown }).error) : `Request failed (${response.status})`;
    throw new Error(message);
  }
  return payload as T;
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map(formatValue).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export const SOURCE_DEFINITIONS = [
  { key: "mymobile", name: "MyMobile", hostname: "mymobile.pk" },
  { key: "daraz", name: "Daraz", hostname: "daraz.pk" },
  { key: "gsmarena", name: "GSMArena", hostname: "gsmarena.com" },
  { key: "mega", name: "Mega.pk", hostname: "mega.pk" },
  { key: "whatamobile", name: "WhataMobile", hostname: "whatamobile.com.pk" },
  { key: "whatmobile", name: "WhatMobile", hostname: "whatmobile.com.pk" },
] as const;
