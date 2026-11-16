import { expect, test } from "@playwright/test";
import { createRun, currentRunId, getJson, getRun, mainTab, openRun, stepRun, tickLabel } from "./helpers";

test("a verification report is tied to the log it checked", async ({ page, request }) => {
  const created = await createRun(request, { label: "e2e verify" });
  const checked = await stepRun(request, created.id, 4);
  await openRun(page, created.id);
  await mainTab(page, "Lab").click();

  const report = page.getByTestId("verify-report");
  await expect(report).toHaveCount(0);
  await page.getByRole("button", { name: "Verify this run" }).click();
  await expect(report).toHaveAttribute("data-stale", "false");
  await expect(report.locator("tbody tr")).toHaveCount(4);
  await expect(report.locator("tbody .chip", { hasText: "pass" })).toHaveCount(4);
  await expect(report).toContainText(`Checked log: ${checked.seq + 1} events up to tick 4`);
  await expect(report).toContainText(checked.head_hash.slice(0, 10));
  // Verifying is a read: it appended nothing.
  expect((await getRun(request, created.id)).head_hash).toBe(checked.head_hash);

  // The run moves on. The old report must say so instead of passing for the new log.
  await page.getByRole("button", { name: "Step", exact: true }).click();
  await expect(tickLabel(page)).toContainText("Tick 5 of 5");
  const moved = await getRun(request, created.id);
  expect(moved.seq).toBeGreaterThan(checked.seq);
  await expect(report).toHaveAttribute("data-stale", "true");
  await expect(report).toContainText("out of date");
  await expect(report).toContainText(`earlier log (${checked.seq + 1} events, tick 4)`);
  await expect(report).toContainText(`The run now has ${moved.seq + 1} events`);

  await page.getByRole("button", { name: "Verify this run" }).click();
  await expect(report).toHaveAttribute("data-stale", "false");
  await expect(report).toContainText(`Checked log: ${moved.seq + 1} events up to tick 5`);
  await expect(report).toContainText(moved.head_hash.slice(0, 10));
});

test("branching, an intervention and a comparison are real operations, and a comparison goes stale", async ({ page, request }) => {
  const parent = await createRun(request, { label: "e2e parent" });
  await stepRun(request, parent.id, 6);
  await openRun(page, parent.id);
  await mainTab(page, "Lab").click();

  await page.getByLabel("Branch label").fill("e2e branch");
  await page.getByRole("button", { name: "Branch here" }).click();
  await expect(page.getByLabel("Select run")).not.toHaveValue(parent.id);
  const branchId = await currentRunId(page);
  let branch = await getRun(request, branchId);
  expect(branch.parent_run_id).toBe(parent.id);
  expect(branch.tick).toBe(6);
  expect(branch.head_hash).toBe((await getRun(request, parent.id)).head_hash);
  await expect(page.getByText(`This run is a branch of`)).toContainText(parent.id);

  // Intervention on the branch only.
  const leak = page.locator(".lab .card", { hasText: "Leak the door log to the press" });
  await leak.getByRole("button", { name: "Apply now" }).click();
  await expect(leak.getByRole("button", { name: "Already applied" })).toBeDisabled();
  branch = await getRun(request, branchId);
  expect(branch.interventions).toEqual(["leak_door_log"]);
  expect((await getRun(request, parent.id)).interventions).toEqual([]);
  const nair = (await getJson(request, `/api/runs/${branchId}/snapshot`)).agents.find((a: any) => a.id === "nair");
  expect(nair.holdings.map((h: any) => h.id)).toContain("E01");

  // Compare with the parent.
  await page.getByLabel("Run to compare with").selectOption(parent.id);
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  const comparison = page.getByTestId("comparison");
  await expect(comparison).toHaveAttribute("data-stale", "false");
  await expect(comparison).toContainText("diverge after tick 6");
  await expect(comparison).toContainText("leak_door_log");
  const facts = await getJson(request, `/api/compare?a=${branchId}&b=${parent.id}`);
  await expect(comparison).toContainText(`share ${facts.common_events} events`);

  // One side moves on: the comparison is marked, and can be refreshed.
  await page.getByRole("button", { name: "Step", exact: true }).click();
  await expect(tickLabel(page)).toContainText("Tick 7 of 7");
  await expect(comparison).toHaveAttribute("data-stale", "true");
  await expect(comparison).toContainText("out of date");
  await comparison.getByRole("button", { name: "Compare again" }).click();
  await expect(comparison).toHaveAttribute("data-stale", "false");

  // Verification passes on a branch that diverged.
  await page.getByRole("button", { name: "Verify this run" }).click();
  await expect(page.getByTestId("verify-report").locator("tbody .chip", { hasText: "pass" })).toHaveCount(4);
});

test("the solution stays on the server until the user reveals it", async ({ page, request }) => {
  const created = await createRun(request, { label: "e2e isolation" });
  await stepRun(request, created.id, 3);

  const bodies: { url: string; text: string }[] = [];
  page.on("response", async (response) => {
    if (!response.url().includes("/api/")) return;
    try {
      bodies.push({ url: response.url(), text: await response.text() });
    } catch {
      // A response with no body (204) has nothing to inspect.
    }
  });

  await openRun(page, created.id);
  await page.getByLabel("Graph perspective").selectOption("okafor");
  await mainTab(page, "Lab").click();
  await page.getByRole("button", { name: "Verify this run" }).click();
  await expect(page.getByTestId("verify-report")).toBeVisible();
  await mainTab(page, "Evaluation").click();
  await expect(page.getByText("The case is still open.")).toBeVisible();
  await expect(page.locator(".verdict")).toHaveCount(0);

  await page.waitForLoadState("networkidle");
  expect(bodies.length).toBeGreaterThan(5);
  for (const body of bodies) {
    for (const forbidden of ['"culprit"', '"solution"', '"key_evidence"', '"truth":', '"agendas"']) {
      expect(body.text.includes(forbidden), `${body.url} contains ${forbidden}`).toBe(false);
    }
  }

  await page.getByRole("button", { name: "Reveal the solution now" }).click();
  await expect(page.locator(".verdict-title")).toContainText("so far");
  await expect(page.locator(".verdict")).toContainText("The culprit is");
  const evaluation = await getJson(request, `/api/runs/${created.id}/evaluation`);
  expect(evaluation.available).toBe(true);
  expect((await getRun(request, created.id)).status).toBe("running"); // revealing does not end the run
});
