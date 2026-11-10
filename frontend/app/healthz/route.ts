export const dynamic = "force-dynamic";

/** Unauthenticated liveness probe for container orchestration. Reveals nothing. */
export function GET() {
  return Response.json({ status: "ok" });
}
