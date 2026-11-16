import { expect, test } from "@playwright/test";
import { agentCard, createRun, getJson, getRun, mainTab, openRun, stepRun } from "./helpers";

test("the agent inspector shows what the server holds for that agent", async ({ page, request }) => {
  const created = await createRun(request, { label: "e2e inspector" });
  await stepRun(request, created.id, 6);
  const snapshot = await getJson(request, `/api/runs/${created.id}/snapshot`);
  const events = await getJson(request, `/api/runs/${created.id}/events`);
  const okafor = snapshot.agents.find((a: any) => a.id === "okafor");
  const decisions = events.filter((e: any) => ["ActionTaken", "ActionRejected"].includes(e.type) && e.data.agent === "okafor");
  expect(okafor.holdings.length).toBeGreaterThan(0);

  await openRun(page, created.id);
  await agentCard(page, okafor.name).click();
  const panel = page.locator(".agent-panel");
  await expect(panel.locator("h2")).toHaveText(okafor.name);

  await expect(panel.getByRole("tab", { name: `Beliefs ${okafor.beliefs.length}` })).toBeVisible();
  await expect(panel.locator(".beliefs > li")).toHaveCount(okafor.beliefs.length);

  await panel.getByRole("tab", { name: `Evidence ${okafor.holdings.length}` }).click();
  await expect(panel.locator(".cards > li")).toHaveCount(okafor.holdings.length);
  const first = snapshot.evidence[okafor.holdings[0].id];
  await expect(panel.locator(".cards > li").first()).toContainText(first.title);
  await expect(panel.locator(".cards > li").first()).toContainText(first.text);

  await panel.getByRole("tab", { name: `Decisions ${decisions.length}` }).click();
  await expect(panel.locator(".cards > li")).toHaveCount(decisions.length);
  const latest = decisions[decisions.length - 1];
  await expect(panel.locator(".cards > li").first()).toContainText(latest.data.trace.reason);
  await expect(panel.locator(".cards > li").first()).toContainText(`event #${latest.seq}`);

  // From a record to its node: content plus the relationships that carry provenance.
  await panel.getByRole("tab", { name: `Evidence ${okafor.holdings.length}` }).click();
  await panel.locator(".cards > li").first().getByRole("button", { name: first.id, exact: true }).click();
  await expect(mainTab(page, "Selection")).toHaveAttribute("aria-selected", "true");
  const detail = page.locator(".detail");
  await expect(detail.locator("h2")).toHaveText(first.title);
  await expect(detail).toContainText(first.text);
  await expect(detail).toContainText("Relationships and provenance");
  const graph = await getJson(request, `/api/runs/${created.id}/graph`);
  const touching = graph.edges.filter((e: any) => e.source === `ev:${first.id}` || e.target === `ev:${first.id}`);
  await expect(detail.locator(".section", { hasText: "Relationships and provenance" }).locator("tbody tr")).toHaveCount(touching.length);
});

test("graph perspective and a policy change are requests to the server", async ({ page, request }) => {
  const created = await createRun(request, { label: "e2e perspective" });
  const before = await stepRun(request, created.id, 5);
  await openRun(page, created.id);

  const asOkafor = page.waitForResponse((r) => r.url().includes(`/api/runs/${created.id}/graph`) && r.url().includes("perspective=okafor"));
  await page.getByLabel("Graph perspective").selectOption("okafor");
  const graph = await (await asOkafor).json();
  expect(graph.perspective).toBe("okafor");
  const held = (await getJson(request, `/api/runs/${created.id}/snapshot`)).agents.find((a: any) => a.id === "okafor").holdings.map((h: any) => h.id);
  expect(graph.nodes.filter((n: any) => n.type === "evidence").map((n: any) => n.ref).sort()).toEqual([...held].sort());

  // "Graph as ..." in the inspector switches the same selector.
  await agentCard(page, "Dr. Ilya Brandt").click();
  const asBrandt = page.waitForResponse((r) => r.url().includes("perspective=brandt"));
  await page.getByRole("button", { name: "Graph as Brandt" }).click();
  await asBrandt;
  await expect(page.getByLabel("Graph perspective")).toHaveValue("brandt");

  // Changing a policy mid-run appends an event and is used from the next tick.
  await agentCard(page, "Det. Mara Okafor").click();
  await page.locator(".agent-panel").getByLabel("Policy").selectOption("hasty");
  await expect(agentCard(page, "Det. Mara Okafor")).toContainText("hasty");
  const after = await getRun(request, created.id);
  expect(after.policies.okafor).toBe("hasty");
  expect(after.seq).toBe(before.seq + 1);
  const events = await getJson(request, `/api/runs/${created.id}/events?after=${before.seq}`);
  expect(events.map((e: any) => e.type)).toEqual(["PolicyChanged"]);
});
