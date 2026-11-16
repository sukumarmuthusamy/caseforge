import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { createRun, openRun, stepRun, tickLabel } from "./helpers";

// The historical-tick slider used to take its value from the snapshot that had last
// arrived, so a key pressed while a request was outstanding started from the old position and
// asked for the same tick again. These tests hold the responses back on purpose, and make the
// earlier ticks the slowest so that answers arrive out of order.

const SNAPSHOT_OR_GRAPH = /\/api\/runs\/[^/]+\/(snapshot|graph)\?(?=.*\btick=\d+)/;

async function delayHistoricalResponses(page: Page) {
  const seen: string[] = [];
  await page.route(SNAPSHOT_OR_GRAPH, async (route) => {
    const tick = Number(new URL(route.request().url()).searchParams.get("tick"));
    await new Promise((resolve) => setTimeout(resolve, Math.max(0, 900 - tick * 150))); // tick 1 is slowest
    seen.push(route.request().url());
    await route.continue();
  });
  return seen;
}

const slider = (page: Page) => page.getByLabel("View tick");

test("rapid arrow keys end where the user asked, with slow and out-of-order responses", async ({ page, request }) => {
  const run = await createRun(request, { scenario: "quiet_substitution", seed: 7, policies: { ibarra: "deceptive" }, label: "e2e slider" });
  await stepRun(request, run.id, 8);
  await openRun(page, run.id);
  await expect(tickLabel(page)).toContainText("Tick 8 of 8");
  await page.getByLabel("Graph perspective").selectOption("hale");

  await slider(page).focus();
  await page.keyboard.press("Home");
  await expect(tickLabel(page)).toContainText("Tick 0 of 8");

  const seen = await delayHistoricalResponses(page);
  const before = await page.evaluate(() => performance.now());
  expect(before).toBeGreaterThan(0);
  // Five presses without waiting for anything: the page has not loaded tick 1 when the fifth arrives.
  for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowRight", { delay: 10 });

  await expect(slider(page)).toHaveValue("5"); // the requested position, at once
  await expect(page.getByTestId("scrub-pending")).toBeVisible(); // while the data for it is still loading
  await expect(tickLabel(page)).toContainText("Tick 5 of 8");
  await expect(page.getByTestId("scrub-pending")).toHaveCount(0);

  // Let every superseded response arrive; none may replace the newest.
  await expect.poll(() => seen.filter((u) => u.includes("/snapshot?")).length, { timeout: 15_000 }).toBeGreaterThanOrEqual(5);
  await expect(tickLabel(page)).toContainText("Tick 5 of 8");
  await expect(slider(page)).toHaveValue("5");
  expect(new URL(seen.filter((u) => u.includes("/graph?")).pop()!).searchParams.get("perspective")).toBe("hale");

  // And back the other way, then to the latest tick.
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowLeft", { delay: 10 });
  await expect(slider(page)).toHaveValue("2");
  await expect(tickLabel(page)).toContainText("Tick 2 of 8");
  for (let i = 0; i < 6; i++) await page.keyboard.press("ArrowRight", { delay: 10 });
  await expect(slider(page)).toHaveValue("8");
  await expect(tickLabel(page)).toContainText("Tick 8 of 8");
  await expect(page.getByText("Showing the latest state")).toBeVisible();
  await expect(page.getByLabel("Graph perspective")).toHaveValue("hale");
});

test("dragging, clicking and Back to latest still work, and the data matches the tick shown", async ({ page, request }) => {
  const run = await createRun(request, { scenario: "quiet_substitution", seed: 7 });
  await stepRun(request, run.id, 6);
  await openRun(page, run.id);
  await delayHistoricalResponses(page);

  await slider(page).fill("3");
  await expect(slider(page)).toHaveValue("3");
  await expect(tickLabel(page)).toContainText("Tick 3 of 6");
  await expect(page.getByText("viewing the past")).toBeVisible();
  const shown = await page.evaluate(async (id) => (await (await fetch(`/api/runs/${id}/snapshot?tick=3`)).json()).seq, run.id);
  expect(shown).toBeGreaterThan(0);

  await slider(page).fill("1");
  await slider(page).fill("4"); // a second jump before the first has loaded
  await expect(slider(page)).toHaveValue("4");
  await expect(tickLabel(page)).toContainText("Tick 4 of 6");

  await page.getByRole("button", { name: "Back to latest" }).click();
  await expect(slider(page)).toHaveValue("6");
  await expect(tickLabel(page)).toContainText("Tick 6 of 6");
  await expect(page.getByTestId("scrub-pending")).toHaveCount(0);
});
