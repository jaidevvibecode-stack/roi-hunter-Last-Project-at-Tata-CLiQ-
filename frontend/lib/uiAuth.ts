/**
 * Basic-auth verification for the dashboard itself (the API has its own auth).
 * Password is stored as scrypt: "<saltHex>:<hashHex>" (generate with `node scripts/hash-ui-password.mjs`).
 * Pure functions — unit-tested in tests/unit/uiAuth.test.ts.
 */
import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";

export interface UiAuthEnv {
  UI_BASIC_USER?: string;
  UI_BASIC_PASSWORD_SCRYPT?: string;
  UI_AUTH_DISABLED?: string;
  NODE_ENV?: string;
}

export type AuthDecision =
  | { allow: true; reason: "disabled" | "authenticated" }
  | { allow: false; status: 401 | 503; reason: string };

export function hashPassword(password: string, saltHex = "", keylen = 32): string {
  const salt = saltHex ? Buffer.from(saltHex, "hex") : randomBytes(16);
  const hash = scryptSync(password, salt, keylen);
  return `${salt.toString("hex")}:${hash.toString("hex")}`;
}

function verifyScrypt(password: string, stored: string): boolean {
  const [saltHex, hashHex] = stored.split(":");
  if (!saltHex || !hashHex) return false;
  const expected = Buffer.from(hashHex, "hex");
  const actual = scryptSync(password, Buffer.from(saltHex, "hex"), expected.length);
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

export function parseBasic(header: string | null): { user: string; pass: string } | null {
  if (!header?.startsWith("Basic ")) return null;
  try {
    const decoded = Buffer.from(header.slice(6), "base64").toString("utf8");
    const i = decoded.indexOf(":");
    return i < 0 ? null : { user: decoded.slice(0, i), pass: decoded.slice(i + 1) };
  } catch {
    return null;
  }
}

/** Fails CLOSED in production: no credentials configured => 503, never "open by default". */
export function decide(authorization: string | null, env: UiAuthEnv): AuthDecision {
  const prod = env.NODE_ENV === "production";
  if (env.UI_AUTH_DISABLED === "true") return { allow: true, reason: "disabled" };
  const configured = Boolean(env.UI_BASIC_USER && env.UI_BASIC_PASSWORD_SCRYPT);
  if (!configured) {
    return prod
      ? { allow: false, status: 503, reason: "UI auth is not configured" }
      : { allow: true, reason: "disabled" }; // local dev convenience only
  }
  const creds = parseBasic(authorization);
  if (!creds) return { allow: false, status: 401, reason: "Authentication required" };
  const userOk = creds.user.length === env.UI_BASIC_USER!.length &&
    timingSafeEqual(Buffer.from(creds.user), Buffer.from(env.UI_BASIC_USER!));
  const passOk = verifyScrypt(creds.pass, env.UI_BASIC_PASSWORD_SCRYPT!); // always run the KDF
  return userOk && passOk ? { allow: true, reason: "authenticated" } : { allow: false, status: 401, reason: "Authentication required" };
}
