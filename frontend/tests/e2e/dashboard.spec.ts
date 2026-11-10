import { expect, test } from "@playwright/test";

const money = /₹[\d.,]+(K|L|Cr)?/;

test.describe("dashboard (demo data)", () => {
  test("overview: demo badge, KPIs, hero chart and segment/ROAS cards render with real numbers", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/overview");
    await expect(page.getByText("DEMO DATA · SYNTHETIC")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    await expect(page.getByText("Ad spend")).toBeVisible();
    await expect(page.getByText(money).first()).toBeVisible();
    await expect(page.getByText(/\d\.\d\dx/).first()).toBeVisible();               // blended ROAS
    await expect(page.locator("canvas").first()).toBeVisible();                     // ECharts drew something
    for (const k of ["Impressions", "CPM", "Link CTR", "CPC", "Orders"]) await expect(page.getByText(k, { exact: true }).first()).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("overview: switching hero metric changes the headline", async ({ page }) => {
    await page.goto("/overview");
    const headline = page.locator("p.text-\\[34px\\]");
    const spend = await headline.innerText();
    await page.getByRole("button", { name: "ROAS", exact: true }).click();
    await expect(headline).not.toHaveText(spend);
    await expect(headline).toHaveText(/\dx|—/);
  });

  test("global filters persist in the URL and survive navigation", async ({ page }) => {
    await page.goto("/overview");
    await page.getByRole("button", { name: "7D", exact: true }).click();
    await page.getByLabel("Attribution model").selectOption("M2");        // two quick changes must both survive
    await expect(page).toHaveURL(/range=7/);
    await expect(page).toHaveURL(/attribution_model=M2/);
    await page.getByRole("link", { name: "Products" }).click();
    await expect(page).toHaveURL(/\/products\?.*range=7/);
    await expect(page).toHaveURL(/attribution_model=M2/);
    await expect(page.getByLabel("Attribution model")).toHaveValue("M2");
    await expect(page.getByRole("button", { name: "7D", exact: true })).toHaveAttribute("data-active", "true");
  });

  test("products: search filters, sort toggles, drawer opens with breakdown, CSV link is proxied", async ({ page }) => {
    await page.goto("/products");
    const rows = page.locator("tbody tr");
    await expect(rows.first()).toBeVisible();
    const total = await page.getByText(/\d+ products/).innerText();

    await page.getByPlaceholder("Search product name or SKU").fill("watch");
    await expect(page.getByText(/\d+ products/)).not.toHaveText(total);
    for (const t of await rows.allInnerTexts()) expect(t.toLowerCase()).toMatch(/watch/);

    await page.getByPlaceholder("Search product name or SKU").fill("");
    await page.getByRole("columnheader", { name: "ROAS" }).click();
    const first = await rows.first().innerText();
    await page.getByRole("columnheader", { name: "ROAS" }).click();
    await expect(rows.first()).not.toHaveText(first);                                // direction flipped

    await rows.first().click();
    await expect(page.getByText("Where the spend went")).toBeVisible();
    await expect(page.locator("aside canvas")).toBeVisible();
    await page.getByRole("button", { name: "ad", exact: true }).click();
    await expect(page.getByRole("button", { name: "Close" })).toBeVisible();
    await page.getByRole("button", { name: "Close" }).click();

    await expect(page.getByRole("link", { name: /Export CSV/ })).toHaveAttribute("href", /^\/api\/proxy\/api\/v1\/export\/products\.csv\?/);
  });

  test("segments: five segment cards and the scatter chart", async ({ page }) => {
    await page.goto("/segments");
    for (const s of ["Stars", "Hidden Gems", "Bleeders", "Zombies", "Insufficient data"]) await expect(page.getByText(s, { exact: true }).first()).toBeVisible();
    await expect(page.locator("canvas").first()).toBeVisible();
    await page.getByRole("button", { name: /Bleeders/ }).click();
    await expect(page.getByText("High spend, ROAS below target — review or exclude")).toBeVisible();
  });

  test("recommendations: recommendation-only banner and SKU export", async ({ page }) => {
    await page.goto("/recommendations");
    await expect(page.getByText("Recommendation-only — nothing is changed in Meta")).toBeVisible();
    await expect(page.getByText(/needs action|opportunity/i).first()).toBeVisible();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: /\d+ SKUs/ }).first().click();
    expect((await download).suggestedFilename()).toMatch(/_skus\.csv$/);
  });

  test("attribution: four models side by side", async ({ page }) => {
    await page.goto("/attribution");
    for (const m of ["M1", "M2", "M3", "M4"]) await expect(page.locator("main").getByText(new RegExp(`^${m} ·`)).first()).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "M4 ROAS" })).toBeVisible();
    await expect(page.locator("tbody tr").first()).toBeVisible();
  });

  test("trends: dual-axis chart renders", async ({ page }) => {
    await page.goto("/trends");
    await expect(page.locator("canvas").first()).toBeVisible();
  });

  test("data health is honest about pending integrations in demo mode", async ({ page }) => {
    await page.goto("/data-health");
    await expect(page.getByText("Integration pending.")).toBeVisible();
    await expect(page.getByText("PENDING").first()).toBeVisible();
    await expect(page.getByText("meta_insights")).toBeVisible();
  });
});

test.describe("server-side proxy is locked down", () => {
  test("only GET and only allow-listed backend paths are reachable", async ({ request }) => {
    expect((await request.get("/api/proxy/docs")).status()).toBe(404);
    expect((await request.get("/api/proxy/openapi.json")).status()).toBe(404);
    expect((await request.get("/api/proxy/api/v1/../../etc/passwd")).status()).toBe(404);
    expect((await request.get("/api/proxy/api/v1/nope-not-allowed!")).status()).toBe(404);
    expect((await request.post("/api/proxy/api/v1/overview")).status()).toBe(405);
    expect((await request.delete("/api/proxy/api/v1/overview")).status()).toBe(405);
  });

  test("security headers are present and the health probe is public", async ({ request }) => {
    const r = await request.get("/healthz");
    expect(r.status()).toBe(200);
    const h = r.headers();
    expect(h["x-frame-options"]).toBe("DENY");
    expect(h["x-content-type-options"]).toBe("nosniff");
    expect(h["content-security-policy"]).toContain("frame-ancestors 'none'");
    expect(h["x-powered-by"]).toBeUndefined();
  });
});
