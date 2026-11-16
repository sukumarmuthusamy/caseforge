import { expect, test } from "@playwright/test";
import { getJson } from "./helpers";

// The counterfactual laboratory page, against the real server: it shows the recorded collection
// as recorded, keeps the ground truth behind a deliberate reveal, runs only what it is asked to,
// labels each figure with where it came from, and opens a playable challenge as an ordinary run.

async function openLab(page: any) {
  await page.goto("/#lab");
  await expect(page.getByTestId("lab-overview")).toBeVisible();
}

test("the overview shows the recorded collection, labelled, with its predictions and limits", async ({ page, request }) => {
  const overview: any = await getJson(request, "/api/lab");
  await openLab(page);

  await expect(page.getByTestId("lab-label")).toContainText("Not an independent benchmark");
  await expect(page.getByTestId("lab-status")).toContainText("stored");
  await expect(page.getByTestId("lab-status")).toContainText(`${overview.stored.runs} playable runs`);
  await expect(page.getByTestId("lab-drift-none")).toBeVisible();

  // One row per registered playable challenge, counts with the run count as denominator.
  const custodian = overview.playable.find((c: any) => c.id === "custodian_hasty");
  const row = page.getByTestId("lab-row-custodian_hasty");
  await expect(row).toContainText(`${custodian.aggregate.categories.wrong_supported}/${custodian.aggregate.runs}`);
  await expect(row).toContainText(`${custodian.aggregate.replay.passed}/${custodian.aggregate.replay.verified}`);
  await expect(page.getByTestId("lab-compare").locator("tbody tr")).toHaveCount(overview.playable.length);

  // Playable and reasoning-only predictions are separate lines; wrong predictions are listed.
  const p = overview.predictions;
  await expect(page.getByTestId("lab-predictions")).toContainText(`${p.playable.right}/${p.playable.of} predictions right`);
  await expect(page.getByTestId("lab-predictions")).toContainText(`${p.reasoning.right}/${p.reasoning.of} predictions right`);
  await expect(page.getByTestId("lab-wrong").locator("tbody tr")).toHaveCount(overview.wrong_predictions.length);
  await expect(page.getByTestId("lab-reasoning").locator("tbody tr")).toHaveCount(overview.reasoning.length);
  await expect(page.getByTestId("lab-limits").locator("li")).toHaveCount(overview.limitations.length);

  // Nothing here names who did it.
  const text = await page.getByTestId("lab-overview").innerText();
  for (const challenge of ["custodian_hasty", "curator_did_it"]) {
    const detail: any = await getJson(request, `/api/lab/challenges/${challenge}?reveal=true`);
    expect(text).not.toContain(detail.ground_truth.question.slice(0, 60));
  }
});

test("the ground truth stays hidden until it is revealed, and can be hidden again", async ({ page, request }) => {
  const truth: any = (await getJson(request, "/api/lab/challenges/custodian_hasty?reveal=true")).ground_truth;
  await openLab(page);
  await page.getByTestId("lab-select-custodian_hasty").click();
  const detail = page.getByTestId("lab-detail");
  await expect(detail).toBeVisible();

  await expect(page.getByTestId("lab-truth-hidden")).toBeVisible();
  await expect(page.getByTestId("lab-ground-truth")).toHaveCount(0);
  await expect(detail).not.toContainText(truth.question.slice(0, 60));
  await expect(page.getByTestId("lab-accused")).toHaveCount(0);

  await page.getByTestId("lab-reveal").click();
  await expect(page.getByTestId("lab-culprit")).toHaveText(truth.culprit);
  await expect(detail).toContainText(truth.question.slice(0, 60));
  await expect(page.getByTestId("lab-accused")).toBeVisible();

  await page.getByTestId("lab-reveal").click();
  await expect(page.getByTestId("lab-ground-truth")).toHaveCount(0);
  await expect(page.getByTestId("lab-truth-hidden")).toBeVisible();
});

test("a challenge page links straight to itself and shows every recorded seed with its replay status", async ({ page, request }) => {
  const stored: any = await getJson(request, "/api/lab/challenges/lie_survives");
  await page.goto("/#lab/lie_survives");
  await expect(page.getByTestId("lab-detail")).toContainText("lie_survives");
  await expect(page.getByTestId("lab-runs").locator("tbody tr")).toHaveCount(stored.stored.runs.length);
  await expect(page.getByTestId("lab-seed-0")).toContainText("verified");
  await expect(page.getByTestId("lab-expectations")).toContainText("Prediction");
  // The wrong prediction for this challenge is marked as wrong, not hidden.
  await expect(page.getByTestId("lab-expectations").getByText("wrong", { exact: true })).toHaveCount(
    stored.stored.aggregate.expectations.filter((e: any) => e.prediction_right === false).length,
  );
});

test("running seeds is explicit, bounded, labelled as executed, compared with the record, and stores nothing", async ({ page, request }) => {
  const before = (await getJson(request, "/api/runs")) as any[];
  await openLab(page);
  await page.getByTestId("lab-select-control").click();

  // Opening a page ran nothing.
  await expect(page.getByTestId("lab-executed")).toHaveCount(0);

  await page.getByTestId("lab-seeds").fill("0-1");
  await page.getByTestId("lab-execute").click();
  const executed = page.getByTestId("lab-executed");
  await expect(executed).toContainText("executed just now");
  await expect(executed).toContainText("Not the recorded collection");
  await expect(page.getByTestId("lab-compared")).toContainText("2 of 2 identical");
  await expect(executed.locator("tbody tr")).toHaveCount(2);

  // More seeds than the bound are refused by the server, and the refusal is shown.
  await page.getByTestId("lab-seeds").fill("0-11");
  await page.getByTestId("lab-execute").click();
  await expect(page.getByTestId("lab-detail").locator(".banner.error")).toContainText("at most 10 seeds");
  await page.getByTestId("lab-seeds").fill("x");
  await expect(page.getByTestId("lab-execute")).toBeDisabled();

  const after = (await getJson(request, "/api/runs")) as any[];
  expect(after.length).toBe(before.length);
});

test("one recorded seed can be replayed on its own", async ({ page }) => {
  await page.goto("/#lab/custodian_hasty");
  await page.getByTestId("lab-replay-3").click();
  const executed = page.getByTestId("lab-executed");
  await expect(executed).toContainText("all four replay levels checked");
  await expect(executed.locator("tbody tr")).toHaveCount(1);
  await expect(executed.getByTestId("lab-seed-3")).toContainText("verified");
  await expect(page.getByTestId("lab-compared")).toContainText("1 of 1 identical");
});

test("a playable challenge opens as an ordinary run that reproduces the recorded head hash", async ({ page, request }) => {
  const stored: any = await getJson(request, "/api/lab/challenges/custodian_hasty");
  const recorded = stored.stored.runs.find((r: any) => r.seed === 3);
  await page.goto("/#lab/custodian_hasty");
  await page.getByTestId("lab-open-3").click();

  // The investigation screens, on a run of the registered variant.
  await expect(page.getByText("Tick 0 of 0")).toBeVisible();
  const runs = (await getJson(request, "/api/runs")) as any[];
  const opened = runs.find((r) => r.label === "lab: custodian_hasty, seed 3");
  expect(opened).toBeTruthy();
  expect(opened.scenario_id).toBe("quiet_substitution.custodian");
  expect(opened.policies.hale).toBe("hasty");
  expect(opened.continuable).toBe(true);

  await page.getByRole("button", { name: "Run to end", exact: true }).click();
  await expect(page.locator(".topbar .chip", { hasText: /closed/ })).toBeVisible();
  const finished: any = await getJson(request, `/api/runs/${opened.id}`);
  expect(finished.head_hash).toBe(recorded.head);

  // And back to the laboratory.
  await page.getByTestId("lab-open").click();
  await expect(page.getByTestId("lab-overview")).toBeVisible();
  await page.getByTestId("lab-back").click();
  await expect(page.getByLabel("Select run")).toBeVisible();
});

test("a reasoning-only fixture shows its items and result, can be run, and has no investigation to open", async ({ page }) => {
  await openLab(page);
  await page.getByTestId("lab-select-two_keyholders").click();
  const detail = page.getByTestId("lab-detail");
  await expect(detail).toContainText("Items handed to the reasoner");
  await expect(page.getByTestId("lab-beliefs")).toBeVisible();
  await expect(page.getByTestId("lab-seeds")).toHaveCount(0);
  await expect(detail.getByRole("button", { name: "open", exact: true })).toHaveCount(0);

  await page.getByTestId("lab-execute").click();
  await expect(page.getByTestId("lab-executed")).toContainText("executed just now");
  await expect(page.getByTestId("lab-compared")).toContainText("1 of 1 identical");
});

test("the laboratory works from the first screen and from the investigation toolbar", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("lab-open").first().click();
  await expect(page.getByTestId("lab-overview")).toBeVisible();
  await page.getByTestId("lab-back").click();
  await expect(page.getByTestId("lab-open").first()).toBeVisible();
});
