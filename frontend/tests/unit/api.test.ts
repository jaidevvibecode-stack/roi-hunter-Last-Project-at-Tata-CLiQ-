import { describe, expect, it } from "vitest";
import { exportUrl, filterQuery, type GlobalFilters } from "../../lib/api";

const f: GlobalFilters = { range: "30", model: "M2", lookback: "7", start: "2026-03-01", end: "2026-03-30" };

describe("filterQuery", () => {
  it("serialises the global filters", () => {
    const q = new URLSearchParams(filterQuery(f));
    expect(q.get("start_date")).toBe("2026-03-01");
    expect(q.get("end_date")).toBe("2026-03-30");
    expect(q.get("attribution_model")).toBe("M2");
    expect(q.get("lookback_days")).toBe("7");
  });

  it("adds extras, skips empty values, and encodes user input", () => {
    const q = filterQuery(f, { sort: "roas", search: "a&b=c", page: 2, empty: "", missing: undefined });
    expect(q).toContain("search=a%26b%3Dc");
    expect(q).toContain("page=2");
    expect(q).not.toContain("empty");
    expect(q).not.toContain("missing");
  });

  it("export link goes through the server-side proxy", () => {
    expect(exportUrl(f, "spend").startsWith("/api/proxy/api/v1/export/products.csv?")).toBe(true);
  });
});
