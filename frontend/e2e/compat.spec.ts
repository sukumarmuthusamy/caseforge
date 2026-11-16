import { expect, test } from "@playwright/test";
import { createRun, getJson, mainTab, openRun, stepRun, tickLabel } from "./helpers";

// A run recorded under other rules is listed, readable and verifiable, and it cannot be continued.
// The server's database is seeded with one (e2e/seed_readonly.py): it was really played with a
// different reasoner constant and stamped as that behaviour.

async function readOnlyRun(request: any) {
  const runs: any[] = await getJson(request, "/api/runs");
  const found = runs.find((r) => r.label === "e2e read-only older rules");
  expect(found, "the seeded read-only run").toBeTruthy();
  return found;
}

test("a run recorded under other rules says so, can be read, and cannot be continued", async ({ page, request }) => {
  const stored = await readOnlyRun(request);
  expect(stored.compatible).toBe(true);
  expect(stored.continuable).toBe(false);
  expect(stored.compatibility.state).toBe("behaviour_changed");
  const before = stored.head_hash;

  await openRun(page, stored.id);
  await expect(page.getByTestId("readonly-banner")).toContainText("read-only");
  await expect(page.getByTestId("readonly-banner")).toContainText(`diverges at event ${stored.compatibility.first_divergence}`);
  await expect(page.getByLabel("Select run").locator("option:checked")).toContainText("read-only");

  // Nothing that adds to the log is offered.
  for (const name of ["Step", "+5", "Run to end", "Play"]) {
    const button = page.getByRole("button", { name, exact: true });
    if (await button.count()) await expect(button.first()).toBeDisabled();
  }
  await mainTab(page, "Lab").click();
  await expect(page.getByTestId("readonly-note")).toBeVisible();
  await expect(page.getByTestId("compatibility-note")).toContainText("behaviour changed");
  for (const button of await page.locator(".cards button").all()) await expect(button).toBeDisabled();

  // The server refuses too, and the log is untouched.
  const refused = await request.post(`/api/runs/${stored.id}/step`, { data: { ticks: 1 } });
  expect(refused.status()).toBe(409);
  expect((await refused.json()).detail).toContain("read-only");
  expect((await getJson(request, `/api/runs/${stored.id}`)).head_hash).toBe(before);

  // It can be read in the past, and verified: the report says where the rules differ.
  await page.getByLabel("View tick").focus();
  await page.keyboard.press("Home");
  await expect(tickLabel(page)).toContainText("Tick 0 of 14");
  await page.getByRole("button", { name: "Back to latest" }).click();
  await page.getByRole("button", { name: "Verify this run" }).click();
  const report = page.getByTestId("verify-report");
  await expect(report).toBeVisible();
  await expect(report).toContainText("FAIL"); // the decision replay
  await expect(report).toContainText(`diverged at event ${stored.compatibility.first_divergence}`);
});

test("a new run is stamped and continues as before", async ({ page, request }) => {
  const created = await createRun(request, { scenario: "quiet_substitution", seed: 5, label: "e2e compat new" });
  await stepRun(request, created.id, 2);
  const run = await getJson(request, `/api/runs/${created.id}`);
  expect(run.continuable).toBe(true);
  expect(run.compatibility.state).toBe("current");
  await openRun(page, created.id);
  await expect(page.getByTestId("readonly-banner")).toHaveCount(0);
  await page.getByRole("button", { name: "Step", exact: true }).click();
  await expect(tickLabel(page)).toContainText("Tick 3 of 3");
});
