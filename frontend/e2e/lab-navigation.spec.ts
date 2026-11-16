import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { getJson } from "./helpers";

// The laboratory page keeps one challenge's detail on screen; the ground
// truth of a challenge is shown only for a deliberate "Reveal" on that challenge. These tests record what
// the browser actually sends and receives (not only what is drawn), because a response that is never
// rendered has still reached the browser.
//
// A and B are two different challenges with different culprits, so a leak is visible in the data.

const A = "control";
const B = "curator_did_it";
const C = "lie_survives";

interface Capture {
  requests: { id: string; url: string; reveal: boolean }[];
  responses: { id: string; reveal: boolean; hasTruth: boolean; revealed: boolean | null }[];
}

const CHALLENGE_URL = /\/api\/lab\/challenges\/([^/?]+)(\/execute|\/open)?(\?.*)?$/;

/** Record every laboratory request and what came back for it, without altering anything. */
async function capture(page: Page): Promise<Capture> {
  const seen: Capture = { requests: [], responses: [] };
  page.on("request", (request) => {
    const match = CHALLENGE_URL.exec(request.url());
    if (match) seen.requests.push({ id: decodeURIComponent(match[1]), url: request.url(), reveal: new URL(request.url()).searchParams.get("reveal") === "true" });
  });
  page.on("response", async (response) => {
    const match = CHALLENGE_URL.exec(response.url());
    if (!match || match[2] || response.request().method() !== "GET") return;
    const reveal = new URL(response.url()).searchParams.get("reveal") === "true";
    try {
      const body = await response.json();
      seen.responses.push({ id: decodeURIComponent(match[1]), reveal, hasTruth: "ground_truth" in body && body.ground_truth != null, revealed: body.revealed ?? null });
    } catch {
      seen.responses.push({ id: decodeURIComponent(match[1]), reveal, hasTruth: false, revealed: null });
    }
  });
  return seen;
}

const forChallenge = <T extends { id: string }>(items: T[], id: string) => items.filter((item) => item.id === id);

async function openLab(page: Page) {
  await page.goto("/#lab");
  await expect(page.getByTestId("lab-overview")).toBeVisible();
}

const detailOf = (page: Page, id: string) => page.getByRole("region", { name: `Challenge ${id}` });

test("revealing one challenge does not reveal the next one on the wire or on the page", async ({ page, request }) => {
  const truthA: any = (await getJson(request, `/api/lab/challenges/${A}?reveal=true`)).ground_truth;
  const truthB: any = (await getJson(request, `/api/lab/challenges/${B}?reveal=true`)).ground_truth;
  expect(truthA.culprit).not.toBe(truthB.culprit);

  await openLab(page);
  const seen = await capture(page);

  await page.getByTestId(`lab-select-${A}`).click();
  await expect(detailOf(page, A)).toBeVisible();
  await page.getByTestId("lab-reveal").click();
  await expect(page.getByTestId("lab-culprit")).toHaveText(truthA.culprit);

  // Move to B without revealing it.
  await page.getByTestId(`lab-select-${B}`).click();
  await expect(detailOf(page, B)).toBeVisible();
  await expect(page.getByTestId("lab-truth-hidden")).toBeVisible();
  await expect(page.getByTestId("lab-ground-truth")).toHaveCount(0);
  await expect(page.getByTestId("lab-reveal")).toHaveText("Reveal the ground truth");
  await expect(detailOf(page, B)).not.toContainText(truthB.question.slice(0, 60));

  // The browser never asked for B's truth, and never received it.
  expect(forChallenge(seen.requests, B).length).toBeGreaterThan(0);
  expect(forChallenge(seen.requests, B).filter((r) => r.reveal)).toEqual([]);
  expect(forChallenge(seen.responses, B).filter((r) => r.hasTruth || r.revealed)).toEqual([]);
  // A's deliberate reveal did reach A.
  expect(forChallenge(seen.responses, A).some((r) => r.reveal && r.hasTruth)).toBe(true);
});

test("a deliberate reveal still works for the challenge it is made on, whichever one that is", async ({ page, request }) => {
  const truthB: any = (await getJson(request, `/api/lab/challenges/${B}?reveal=true`)).ground_truth;
  await openLab(page);
  const seen = await capture(page);

  await page.getByTestId(`lab-select-${A}`).click();
  await page.getByTestId("lab-reveal").click();
  await expect(page.getByTestId("lab-ground-truth")).toBeVisible();

  await page.getByTestId(`lab-select-${B}`).click();
  await expect(page.getByTestId("lab-truth-hidden")).toBeVisible();
  await page.getByTestId("lab-reveal").click();
  await expect(page.getByTestId("lab-culprit")).toHaveText(truthB.culprit);
  await expect(page.getByTestId("lab-accused")).toBeVisible();
  expect(forChallenge(seen.requests, B).some((r) => r.reveal)).toBe(true);

  // Hiding it again goes back to the redacted form, and keeps B selected.
  await page.getByTestId("lab-reveal").click();
  await expect(page.getByTestId("lab-ground-truth")).toHaveCount(0);
  await expect(detailOf(page, B)).toBeVisible();
});

test("a slow reveal response for one challenge cannot show up on the challenge selected after it", async ({ page, request }) => {
  const truthA: any = (await getJson(request, `/api/lab/challenges/${A}?reveal=true`)).ground_truth;
  await openLab(page);
  const seen = await capture(page);

  // Hold A's revealed answer back until B has been selected and has loaded.
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route(new RegExp(`/api/lab/challenges/${A}\\?reveal=true`), async (route) => {
    await gate;
    await route.continue();
  });

  await page.getByTestId(`lab-select-${A}`).click();
  await expect(detailOf(page, A)).toBeVisible();
  await page.getByTestId("lab-reveal").click(); // its request is now parked at the route
  await page.getByTestId(`lab-select-${B}`).click();
  await expect(detailOf(page, B)).toBeVisible();
  await expect(page.getByTestId("lab-truth-hidden")).toBeVisible();

  const late = page.waitForResponse((r) => r.url().includes(`/api/lab/challenges/${A}?reveal=true`));
  release();
  await late;
  await page.waitForTimeout(300); // let a late response, if it were going to render, render

  await expect(detailOf(page, B)).toBeVisible();
  await expect(page.getByTestId("lab-ground-truth")).toHaveCount(0);
  await expect(page.getByTestId("lab-culprit")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(truthA.question.slice(0, 60));
  expect(forChallenge(seen.requests, B).filter((r) => r.reveal)).toEqual([]);
  expect(forChallenge(seen.responses, B).filter((r) => r.hasTruth)).toEqual([]);
});

test("rapid changes of selection never send a reveal for a challenge that was not revealed", async ({ page }) => {
  await openLab(page);
  const seen = await capture(page);

  await page.getByTestId(`lab-select-${A}`).click();
  await page.getByTestId("lab-reveal").click();
  for (const id of [B, C, A, B, C]) await page.getByTestId(`lab-select-${id}`).click({ delay: 0 });
  await expect(detailOf(page, C)).toBeVisible();
  await page.waitForTimeout(500);

  expect(seen.requests.filter((r) => r.id !== A && r.reveal)).toEqual([]);
  expect(seen.responses.filter((r) => r.id !== A && (r.hasTruth || r.revealed))).toEqual([]);
  // Re-selecting A after leaving it starts from the redacted form: a reveal is per visit.
  await page.getByTestId(`lab-select-${A}`).click();
  await expect(page.getByTestId("lab-truth-hidden")).toBeVisible();
  await expect(page.getByTestId("lab-reveal")).toHaveText("Reveal the ground truth");
});

test("an execution that finishes after another challenge was selected is not shown there, and cannot open runs for it", async ({ page, request }) => {
  const runsBefore = ((await getJson(request, "/api/runs")) as any[]).length;
  await openLab(page);
  const seen = await capture(page);

  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  await page.route(new RegExp(`/api/lab/challenges/${A}/execute`), async (route) => {
    await gate;
    await route.continue();
  });

  await page.getByTestId(`lab-select-${A}`).click();
  await page.getByTestId("lab-seeds").fill("0-1");
  await page.getByTestId("lab-execute").click(); // parked
  await page.getByTestId(`lab-select-${B}`).click();
  await expect(detailOf(page, B)).toBeVisible();
  // B's page starts with its own loading and execution state: nothing is busy, nothing was executed.
  await expect(page.getByTestId("lab-executed")).toHaveCount(0);
  await expect(page.getByTestId("lab-execute")).toBeEnabled();

  const late = page.waitForResponse((r) => r.url().includes(`/api/lab/challenges/${A}/execute`));
  release();
  await late;
  await page.waitForTimeout(300);

  await expect(detailOf(page, B)).toBeVisible();
  await expect(page.getByTestId("lab-executed")).toHaveCount(0);
  await expect(page.getByTestId("lab-compared")).toHaveCount(0);
  expect(seen.requests.filter((r) => r.url.endsWith("/open"))).toEqual([]);
  expect(((await getJson(request, "/api/runs")) as any[]).length).toBe(runsBefore); // executing stores nothing

  // B's own execution is B's, and its Open action names B.
  await page.getByTestId("lab-seeds").fill("0");
  await page.getByTestId("lab-execute").click();
  await expect(page.getByTestId("lab-executed")).toContainText("executed just now");
  const opened = page.waitForRequest((r) => /\/api\/lab\/challenges\/[^/]+\/open$/.test(r.url()));
  await page.getByTestId("lab-executed").getByTestId("lab-open-0").click();
  expect(decodeURIComponent((await opened).url())).toContain(`/api/lab/challenges/${B}/open`);
});

test("a crafted challenge link cannot inject a reveal parameter", async ({ page }) => {
  const seen = await capture(page);
  await page.goto("/#lab/control%3Freveal%3Dtrue");
  await expect(page.getByTestId("lab-overview")).toBeVisible();
  await expect(page.getByTestId("lab-detail")).toHaveCount(0); // no such challenge
  await expect(page.getByTestId("lab-ground-truth")).toHaveCount(0);
  await expect(page.getByTestId("lab-culprit")).toHaveCount(0);

  expect(seen.requests.filter((r) => r.reveal)).toEqual([]);
  // The identifier is one encoded path segment, so it cannot become a query string.
  expect(seen.requests.map((r) => new URL(r.url).search).filter((s) => s !== "")).toEqual([]);
  expect(seen.requests.some((r) => r.url.includes("control%3Freveal%3Dtrue") || r.url.includes("control?reveal"))).toBe(true);
});
