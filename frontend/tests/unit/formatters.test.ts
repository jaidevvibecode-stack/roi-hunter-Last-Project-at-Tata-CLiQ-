import { describe, expect, it } from "vitest";
import { fmt, fmtCount, fmtCurrency, fmtDelta, fmtPct, fmtRoas } from "../../lib/formatters";

describe("formatters", () => {
  it("renders NULL / NaN / undefined as an em dash — never 0 or Infinity", () => {
    for (const f of [fmt, fmtCount, fmtPct, fmtRoas, fmtDelta, fmtCurrency] as ((v: number | null | undefined) => string)[]) {
      expect(f(null)).toBe("—");
      expect(f(undefined)).toBe("—");
      expect(f(NaN)).toBe("—");
    }
  });

  it("formats INR in thousands / lakh / crore", () => {
    expect(fmtCurrency(999)).toBe("₹999.00");
    expect(fmtCurrency(12_500)).toBe("₹12.5K");
    expect(fmtCurrency(1_250_000)).toBe("₹12.50L");
    expect(fmtCurrency(25_000_000)).toBe("₹2.50Cr");
    expect(fmtCurrency(-1_250_000)).toBe("₹-12.50L");
  });

  it("formats ratios", () => {
    expect(fmtPct(0.0324)).toBe("3.24%");
    expect(fmtRoas(2.345)).toBe("2.35x");
    expect(fmtRoas(0)).toBe("0.00x"); // a real zero is shown, unlike a missing value
  });

  it("formats counts compactly", () => {
    expect(fmtCount(950)).toBe("950");
    expect(fmtCount(12_300)).toBe("12.3K");
    expect(fmtCount(4_560_000)).toBe("4.6M");
  });

  it("signs deltas", () => {
    expect(fmtDelta(12.34)).toBe("+12.3%");
    expect(fmtDelta(-5)).toBe("-5.0%");
    expect(fmtDelta(0)).toBe("0.0%");
  });
});
