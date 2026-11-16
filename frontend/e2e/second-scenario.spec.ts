import { expect, test } from "@playwright/test";
import { agentCard, createRun, currentRunId, getJson, getRun, mainTab, openRun, tickLabel } from "./helpers";

const SECOND = "quiet_substitution";
const VERDICT: Record<string, string> = { solved: "Solved", wrong_accusation: "Wrong accusation", unresolved: "Unresolved" };

test("the second case is chosen in the dialog, played to its end and scored", async ({ page, request }) => {
  const scenarios: any[] = await getJson(request, "/api/scenarios");
  const first = scenarios.find((s) => s.id === "missing_prototype");
  const second = scenarios.find((s) => s.id === SECOND);
  expect(second, "the second scenario is installed").toBeTruthy();

  // Nothing the page receives while the case is open may carry the answer.
  const bodies: { url: string; text: string }[] = [];
  let open = true;
  page.on("response", async (response) => {
    if (!open || !response.url().includes("/api/")) return;
    try {
      bodies.push({ url: response.url(), text: await response.text() });
    } catch {
      // nothing to inspect
    }
  });

  await page.goto("/");
  const chooser = page.getByRole("button", { name: "Choose seed and policies..." });
  const newRun = page.getByRole("button", { name: "New run" });
  await expect(chooser.or(newRun)).toBeVisible();
  await ((await chooser.isVisible()) ? chooser : newRun).click();
  const dialog = page.getByRole("dialog", { name: "New investigation" });

  // A choice made for the first case's agents must not travel to the second:
  // the server rejects a policy for an agent the case does not have.
  await dialog.locator(".policy-row", { hasText: first.agents[0].name }).locator("select").selectOption("hasty");
  await dialog.getByLabel("Scenario").selectOption(SECOND);
  await expect(dialog.locator(".quote")).toHaveText(second.briefing);
  await expect(dialog.locator(".policy-row")).toHaveCount(second.agents.length);
  for (const agent of second.agents) {
    await expect(dialog.locator(".policy-row", { hasText: agent.name }).locator("select")).toHaveValue("baseline");
  }
  await expect(dialog.locator(".policy-row", { hasText: first.agents[0].name })).toHaveCount(0);

  await dialog.getByLabel("Seed").fill("7");
  // An older run may already be on screen at "Tick 0 of 0", so that label does not say the new run is
  // open. Take the new run's id from the server's reply and wait until the page has loaded that run.
  const [created] = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/api/runs") && r.request().method() === "POST").then((r) => r.json()),
    dialog.getByRole("button", { name: "Open the case" }).click(),
  ]);
  await expect(page.getByLabel("Select run")).toHaveValue(created.id);
  await expect(tickLabel(page)).toContainText("Tick 0 of 0");
  const id = await currentRunId(page);
  expect(id).toBe(created.id);
  let run = await getRun(request, id);
  expect(run.scenario_id).toBe(SECOND);
  expect(Object.keys(run.policies).sort()).toEqual(second.agents.map((a: any) => a.id).sort());
  expect(Object.values(run.policies).every((name) => name === "baseline")).toBe(true);

  // The page is showing this case, not the first one.
  await expect(page.locator(".topbar")).toContainText(second.title);
  for (const agent of second.agents) await expect(agentCard(page, agent.name)).toBeVisible();
  await expect(agentCard(page, first.agents[0].name)).toHaveCount(0);

  await page.locator(".transport").getByRole("button", { name: "+5", exact: true }).click();
  await expect(tickLabel(page)).toContainText("Tick 5 of 5");
  const snapshot = await getJson(request, `/api/runs/${id}/snapshot`);
  await expect(page.locator(".stat", { hasText: "evidence found" }).first()).toContainText(`${snapshot.progress.evidence_discovered}/${second.evidence_total}`);

  await page.waitForLoadState("networkidle");
  // Only this run and the scenario list: on arrival the page showed an older run,
  // which may be closed, and a closed run is allowed to show its solution.
  const mine = bodies.filter((body) => body.url.includes(`/runs/${id}`) || body.url.endsWith("/api/scenarios"));
  expect(mine.some((body) => body.url.includes("/snapshot"))).toBe(true);
  for (const body of mine) {
    for (const forbidden of ['"culprit"', '"solution"', '"key_evidence"', '"agendas"', '"protects"']) {
      expect(body.text.includes(forbidden), `${body.url} contains ${forbidden}`).toBe(false);
    }
  }
  open = false;

  await page.getByRole("button", { name: "Run to end" }).click();
  await expect(page.locator(".topbar .chip")).toContainText("closed");
  run = await getRun(request, id);
  expect(run.status).toBe("closed");

  const evaluation = (await getJson(request, `/api/runs/${id}/evaluation`)).result;
  await mainTab(page, "Evaluation").click();
  await expect(page.locator(".verdict-title")).toHaveText(VERDICT[evaluation.outcome]);
  const names = Object.fromEntries(second.suspects.map((s: any) => [s.id, s.name]));
  await expect(page.locator(".verdict")).toContainText(`The culprit is ${names[evaluation.culprit]}`);
  // This case has no publisher: the panel says so instead of showing empty ratios.
  expect(evaluation.claims.items.length).toBe(0);
  await expect(page.locator(".evaluation .section", { hasText: "Public claims" })).toContainText("Nobody published anything.");

  await mainTab(page, "Lab").click();
  await page.getByRole("button", { name: "Verify this run" }).click();
  await expect(page.getByTestId("verify-report").locator("tbody .chip", { hasText: "pass" })).toHaveCount(4);
});

test("in the second case a registrar who holds a record back is caught and bypassed", async ({ page, request }) => {
  const created = await createRun(request, { scenario: SECOND, seed: 3, policies: { ibarra: "deceptive" }, label: "e2e second deceptive" });
  const response = await request.post(`/api/runs/${created.id}/step`, { data: { ticks: 40 } });
  expect(response.ok()).toBeTruthy();
  const evaluation = (await getJson(request, `/api/runs/${created.id}/evaluation`)).result;
  const deception = evaluation.deception;
  // The premise of this test; if policy tuning changes it, pick another seed.
  expect(deception.answers_with_withholding).toBeGreaterThan(0);
  expect(deception.escalations.length).toBeGreaterThan(0);

  await openRun(page, created.id);
  await expect(page.locator(".topbar .chip")).toContainText("closed");
  await mainTab(page, "Evaluation").click();
  const section = page.locator(".evaluation .section", { hasText: "Deception" });
  await expect(section.getByTestId("deception-agenda")).toContainText("Lucia Ibarra was covering for Dana Marsh");
  await expect(section.getByTestId("deception-items").locator("tr")).toHaveCount(deception.items.length);
  await expect(section).toContainText(`${deception.noticed.num}/${deception.noticed.den}`);
  const takeover = deception.escalations[0];
  await expect(section).toContainText(`Tick ${takeover.tick}: Insp. Nora Hale took direct access to ${takeover.sources.length} sources over Lucia Ibarra's head.`);

  // The inspector's own panel shows what she caught and what she did about it.
  await agentCard(page, "Insp. Nora Hale").click();
  const hale = (await getJson(request, `/api/runs/${created.id}/snapshot`)).agents.find((a: any) => a.id === "hale");
  expect(hale.discrepancies.length).toBeGreaterThan(0);
  await expect(page.getByTestId("discrepancies").locator("div", { hasText: "left out" })).toHaveCount(hale.discrepancies.length);
  await expect(page.getByTestId("discrepancies")).toContainText("Took direct access to the sources of Lucia Ibarra.");
});
