import { expect } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

// Expectations are read from the server through the API, never hard-coded, so
// the tests keep checking "the page shows what the backend holds" when agent
// behaviour changes.

export interface Run {
  id: string;
  tick: number;
  seq: number;
  status: string;
  scenario_id: string;
  head_hash: string;
  parent_run_id: string | null;
  policies: Record<string, string>;
  interventions: string[];
  accused: string | null;
}

export async function createRun(request: APIRequestContext, body: { scenario?: string; seed?: number; policies?: Record<string, string>; label?: string } = {}): Promise<Run> {
  const response = await request.post("/api/runs", {
    data: { scenario_id: body.scenario ?? "missing_prototype", seed: body.seed ?? 7, policies: body.policies ?? {}, label: body.label ?? "" },
  });
  expect(response.status()).toBe(201);
  return response.json();
}

export async function stepRun(request: APIRequestContext, id: string, ticks: number): Promise<Run> {
  const response = await request.post(`/api/runs/${id}/step`, { data: { ticks } });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).run;
}

export async function getRun(request: APIRequestContext, id: string): Promise<Run> {
  const response = await request.get(`/api/runs/${id}`);
  expect(response.ok()).toBeTruthy();
  return response.json();
}

export async function getJson(request: APIRequestContext, path: string): Promise<any> {
  const response = await request.get(path);
  expect(response.ok(), path).toBeTruthy();
  return response.json();
}

/** Load the app on a given run and wait until that run is on screen. */
export async function openRun(page: Page, id: string): Promise<void> {
  await page.goto(`/#run=${id}`);
  await expect(page.getByLabel("Select run")).toHaveValue(id);
}

export const tickLabel = (page: Page) => page.locator(".scrub-label");

export const mainTab = (page: Page, name: "Agent" | "Selection" | "Lab" | "Evaluation") => page.locator(".main-tabs").getByRole("tab", { name, exact: true });

// Matched on the card's own heading: another agent's card may name this person as its suspect.
export const agentCard = (page: Page, name: string) => page.locator(".agent-card").filter({ has: page.locator(".agent-card-head b", { hasText: name }) });

/** The run currently selected in the top bar. */
export const currentRunId = (page: Page) => page.getByLabel("Select run").inputValue();
