import { expect, test } from "@playwright/test";
import { createRun, currentRunId, getJson, getRun, mainTab, openRun, stepRun, tickLabel } from "./helpers";

const VERDICT: Record<string, string> = { solved: "Solved", wrong_accusation: "Wrong accusation", unresolved: "Unresolved" };

test("a case can be opened from the UI, stepped and run to its end", async ({ page, request }) => {
  await page.goto("/");
  // The welcome screen shows when no run exists; otherwise the top bar offers "New run".
  const chooser = page.getByRole("button", { name: "Choose seed and policies..." });
  const newRun = page.getByRole("button", { name: "New run" });
  await expect(chooser.or(newRun)).toBeVisible();
  await ((await chooser.isVisible()) ? chooser : newRun).click();

  const dialog = page.getByRole("dialog", { name: "New investigation" });
  await dialog.getByLabel("Seed").fill("7");
  await dialog.getByPlaceholder("Optional name for this run").fill("e2e ui run");
  await dialog.getByRole("button", { name: "Open the case" }).click();

  await expect(tickLabel(page)).toContainText("Tick 0 of 0");
  const id = await currentRunId(page);
  expect((await getRun(request, id)).tick).toBe(0);

  await page.getByRole("button", { name: "Step", exact: true }).click();
  await expect(tickLabel(page)).toContainText("Tick 1 of 1");
  let run = await getRun(request, id);
  expect(run.tick).toBe(1);
  await expect(page.locator(".topbar")).toContainText(`${run.seq + 1} events`);

  await page.locator(".transport").getByRole("button", { name: "+5", exact: true }).click();
  await expect(tickLabel(page)).toContainText("Tick 6 of 6");
  expect((await getRun(request, id)).tick).toBe(6);

  await page.getByRole("button", { name: "Run to end" }).click();
  await expect(page.locator(".topbar .chip")).toContainText("closed");
  run = await getRun(request, id);
  expect(run.status).toBe("closed");
  await expect(tickLabel(page)).toContainText(`Tick ${run.tick} of ${run.tick}`);
  await expect(page.locator(".topbar")).toContainText(`${run.seq + 1} events`);
  await expect(page.getByRole("button", { name: "Step", exact: true })).toBeDisabled();

  // The evaluation on screen is the server's evaluation.
  const evaluation = await getJson(request, `/api/runs/${id}/evaluation`);
  expect(evaluation.available).toBe(true);
  await mainTab(page, "Evaluation").click();
  await expect(page.locator(".verdict-title")).toHaveText(VERDICT[evaluation.result.outcome]);
  await expect(page.locator(".verdict")).toContainText("The culprit is");
});

test("time travel shows the past without changing the run", async ({ page, request }) => {
  const created = await createRun(request, { label: "e2e time travel" });
  const before = await stepRun(request, created.id, 8);
  await openRun(page, created.id);
  await expect(tickLabel(page)).toContainText("Tick 8 of 8");

  const found = page.locator(".stat", { hasText: "evidence found" }).first();
  const latest = await getJson(request, `/api/runs/${created.id}/snapshot`);
  await expect(found).toContainText(`${latest.progress.evidence_discovered}/${latest.progress.evidence_total}`);

  // Keyboard on the slider: Home goes to the start of the run.
  await page.getByLabel("View tick").focus();
  await page.keyboard.press("Home");
  await expect(tickLabel(page)).toContainText("Tick 0 of 8");
  await expect(page.getByText("viewing the past")).toBeVisible();
  const start = await getJson(request, `/api/runs/${created.id}/snapshot?tick=0`);
  expect(start.progress.evidence_discovered).toBeLessThan(latest.progress.evidence_discovered);
  await expect(found).toContainText(`${start.progress.evidence_discovered}/${start.progress.evidence_total}`);
  // Stepping is not offered while looking at the past.
  await expect(page.getByRole("button", { name: "Step", exact: true })).toBeDisabled();

  await page.getByRole("button", { name: "Back to latest" }).click();
  await expect(tickLabel(page)).toContainText("Tick 8 of 8");

  // The timeline jumps to a tick as well.
  await page.getByRole("group", { name: "Timeline filter" }).getByRole("button", { name: "All", exact: true }).click();
  await page.getByRole("button", { name: "Tick 3", exact: true }).click();
  await expect(tickLabel(page)).toContainText("Tick 3 of 8");
  const third = await getJson(request, `/api/runs/${created.id}/snapshot?tick=3`);
  await expect(found).toContainText(`${third.progress.evidence_discovered}/${third.progress.evidence_total}`);

  // Looking back changed nothing on the server.
  const after = await getRun(request, created.id);
  expect(after.head_hash).toBe(before.head_hash);
  expect(after.tick).toBe(8);
});

test("play advances the run tick by tick and pause stops it", async ({ page, request }) => {
  const created = await createRun(request, { label: "e2e play" });
  await openRun(page, created.id);
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeVisible();
  await expect.poll(async () => (await getRun(request, created.id)).tick, { timeout: 15_000 }).toBeGreaterThanOrEqual(2);

  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(page.getByRole("button", { name: "Play", exact: true })).toBeVisible();
  await page.waitForTimeout(1200); // lets a request that was already in flight land
  const paused = await getRun(request, created.id);
  await page.waitForTimeout(1800); // longer than two play intervals
  const later = await getRun(request, created.id);
  expect(later.tick).toBe(paused.tick);
  expect(later.status).toBe("running");
  await expect(tickLabel(page)).toContainText(`Tick ${paused.tick} of ${paused.tick}`);
});
