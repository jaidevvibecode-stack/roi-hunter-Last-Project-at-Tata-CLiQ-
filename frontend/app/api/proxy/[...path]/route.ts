/**
 * Server-side proxy to the FastAPI backend.
 * - Backend URL and basic-auth credentials live in SERVER-ONLY env vars (never NEXT_PUBLIC_*),
 *   so the browser never sees them.
 * - GET only, and only the backend's /api/v1/* and /health paths are reachable.
 */
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const BACKEND = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
const ALLOWED = /^(api\/v1\/[a-z0-9_\-./]+|health)$/i;

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> }
) {
  const { path } = await ctx.params;
  const target = path.join("/");
  if (target.includes("..") || !ALLOWED.test(target)) {
    return NextResponse.json({ detail: "Not found" }, { status: 404 });
  }

  const headers: Record<string, string> = {};
  // pass the real client address so the API can rate-limit per user (it only honours this when TRUST_FORWARDED_FOR=true)
  const xff = req.headers.get("x-forwarded-for");
  if (xff) headers["X-Forwarded-For"] = xff;
  const user = process.env.BACKEND_BASIC_USER;
  const pass = process.env.BACKEND_BASIC_PASSWORD;
  if (user && pass) {
    headers.Authorization = "Basic " + Buffer.from(`${user}:${pass}`).toString("base64");
  }

  try {
    const upstream = await fetch(`${BACKEND}/${target}${req.nextUrl.search}`, {
      headers,
      cache: "no-store",
    });
    const body = await upstream.arrayBuffer();
    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
        "content-disposition": upstream.headers.get("content-disposition") ?? "",
        "cache-control": "no-store",
      },
    });
  } catch {
    return NextResponse.json({ detail: "Backend unreachable" }, { status: 502 });
  }
}
