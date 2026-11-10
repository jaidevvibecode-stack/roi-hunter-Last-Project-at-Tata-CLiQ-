/**
 * Next.js 16 `proxy` (formerly middleware): gates EVERY page and the /api/proxy route behind basic auth.
 * Fails closed in production when credentials are not configured. See lib/uiAuth.ts.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { decide } from "./lib/uiAuth";

export function proxy(request: NextRequest) {
  const d = decide(request.headers.get("authorization"), process.env);
  if (d.allow) return NextResponse.next();
  return new NextResponse(d.reason, {
    status: d.status,
    headers: d.status === 401 ? { "WWW-Authenticate": 'Basic realm="ROI Hunter", charset="UTF-8"' } : {},
  });
}

export const config = {
  // everything except static assets and the unauthenticated container health endpoint
  matcher: ["/((?!_next/static|_next/image|favicon.ico|healthz).*)"],
};
