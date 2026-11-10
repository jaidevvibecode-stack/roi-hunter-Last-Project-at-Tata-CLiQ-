import { describe, expect, it } from "vitest";
import { decide, hashPassword, parseBasic } from "../../lib/uiAuth";

const basic = (u: string, p: string) => "Basic " + Buffer.from(`${u}:${p}`).toString("base64");
const env = { UI_BASIC_USER: "tata", UI_BASIC_PASSWORD_SCRYPT: hashPassword("s3cret! with: colon"), NODE_ENV: "production" };

describe("dashboard auth", () => {
  it("allows correct credentials, including passwords containing a colon", () => {
    expect(decide(basic("tata", "s3cret! with: colon"), env)).toEqual({ allow: true, reason: "authenticated" });
  });

  it("rejects missing, wrong-password and wrong-user requests with 401", () => {
    for (const h of [null, "Bearer x", basic("tata", "nope"), basic("evil", "s3cret! with: colon"), "Basic !!!notbase64"]) {
      const d = decide(h, env);
      expect(d).toMatchObject({ allow: false, status: 401 });
    }
  });

  it("FAILS CLOSED in production when credentials are not configured", () => {
    expect(decide(null, { NODE_ENV: "production" })).toMatchObject({ allow: false, status: 503 });
    expect(decide(basic("a", "b"), { NODE_ENV: "production", UI_BASIC_USER: "a" })).toMatchObject({ allow: false, status: 503 });
  });

  it("is open only in local dev, or when explicitly disabled", () => {
    expect(decide(null, { NODE_ENV: "development" })).toMatchObject({ allow: true });
    expect(decide(null, { NODE_ENV: "production", UI_AUTH_DISABLED: "true" })).toMatchObject({ allow: true });
    expect(decide(null, { NODE_ENV: "production", UI_AUTH_DISABLED: "yes" })).toMatchObject({ allow: false });
  });

  it("hashes are salted and verify only the right password", () => {
    expect(hashPassword("x")).not.toBe(hashPassword("x"));
    expect(parseBasic(basic("u", "p:q"))).toEqual({ user: "u", pass: "p:q" });
    expect(parseBasic("Basic ")).toBeNull();
  });
});
