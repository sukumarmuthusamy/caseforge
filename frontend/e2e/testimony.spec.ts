import { expect, test } from "@playwright/test";
import { agentCard, createRun, getJson, mainTab, openRun, stepRun, tickLabel } from "./helpers";

const SECOND = "quiet_substitution";
const ALIBI = "at(marsh,great_hall,thu_evening)";

test("what was said, what the listener made of it and whose word was caught out are on the page", async ({ page, request }) => {
  const created = await createRun(request, { scenario: SECOND, seed: 7, policies: { ibarra: "deceptive" }, label: "e2e testimony" });
  await stepRun(request, created.id, 8);
  const snapshot = await getJson(request, `/api/runs/${created.id}/snapshot`);
  expect(snapshot.status).toBe("running");
  const name = (id: string) => snapshot.entities[id].name;
  const hale = snapshot.agents.find((a: any) => a.id === "hale");
  const ibarra = snapshot.agents.find((a: any) => a.id === "ibarra");
  const involving = (agent: string) => snapshot.statements.filter((s: any) => s.speaker === agent || s.recipient === agent);
  const lie = snapshot.statements.find((s: any) => s.speaker === "ibarra" && s.recipient === "hale" && s.proposition === ALIBI);
  expect(lie, "the registrar has vouched for the conservator").toBeTruthy();
  expect(lie.grounds).toBe("none");
  expect(lie.stances.length).toBeGreaterThan(1); // believed first, then not

  // Nothing the page receives while the case is open says whether a statement was true.
  const bodies: { url: string; text: string }[] = [];
  page.on("response", async (response) => {
    if (!response.url().includes(`/api/runs/${created.id}`) && !response.url().endsWith("/api/scenarios")) return;
    try {
      bodies.push({ url: response.url(), text: await response.text() });
    } catch {
      // nothing to inspect
    }
  });

  await openRun(page, created.id);
  await expect(tickLabel(page)).toContainText("Tick 8 of 8");

  // The listener: every statement she was party to, each with the path of what she made of it.
  await agentCard(page, hale.name).click();
  const panel = page.locator(".agent-panel");
  await panel.getByRole("tab", { name: `Said ${involving("hale").length}` }).click();
  await expect(panel.getByTestId("statement")).toHaveCount(involving("hale").length);
  const card = panel.getByTestId("statement").filter({ has: page.getByRole("button", { name: lie.id, exact: true }) });
  await expect(card).toContainText(`${name("ibarra")} → ${name("hale")}`);
  await expect(card).toContainText(lie.text);
  await expect(card.getByTestId("stance-trail").locator(".chip")).toHaveCount(lie.stances.length);
  for (const stance of lie.stances) {
    await expect(card.getByTestId("stance-trail")).toContainText(`${stance.stance} t${stance.tick}`);
  }
  await expect(card.getByTestId("grounds")).toContainText("had nothing for it");

  // Her judgment of the speaker, with the claim the evidence contradicts.
  const seen = hale.credibility.find((c: any) => c.speaker === "ibarra");
  expect(seen.standing).toBe("impeached");
  await expect(page.getByTestId("credibility").locator("> div[data-testid^='credibility-']")).toHaveCount(hale.credibility.length);
  await expect(page.getByTestId("credibility-ibarra")).toContainText("caught out");
  await expect(page.getByTestId("credibility-ibarra")).toContainText(seen.refuted[0].text);

  // The speaker: what she saw for herself, and no judgment of her own about herself.
  await agentCard(page, ibarra.name).click();
  await panel.getByRole("tab", { name: `Said ${involving("ibarra").length}` }).click();
  await expect(panel.getByTestId("observations")).toContainText(ibarra.observations[0].text);
  await expect(panel.getByTestId("statement")).toHaveCount(involving("ibarra").length);

  // From the statement to its node in the graph.
  await agentCard(page, hale.name).click();
  await panel.getByRole("tab", { name: `Said ${involving("hale").length}` }).click();
  await card.getByRole("button", { name: lie.id, exact: true }).click();
  await expect(mainTab(page, "Selection")).toHaveAttribute("aria-selected", "true");
  const detail = page.locator(".detail");
  await expect(detail.getByTestId("statement-detail")).toContainText(name("ibarra"));
  await expect(detail.getByTestId("statement-detail")).toContainText("had nothing for it");
  const graph = await getJson(request, `/api/runs/${created.id}/graph`);
  const touching = graph.edges.filter((e: any) => e.source === `st:${lie.id}` || e.target === `st:${lie.id}`);
  await expect(detail.locator(".section", { hasText: "Relationships and provenance" }).locator("tbody tr")).toHaveCount(touching.length);
  expect(graph.edges.some((e: any) => e.id === "doubts:ent:hale>ent:ibarra")).toBe(true);

  // In the listener's own graph the speaker's grounds are absent: she was not told.
  const asHale = page.waitForResponse((r) => r.url().includes(`/api/runs/${created.id}/graph`) && r.url().includes("perspective=hale"));
  await page.getByLabel("Graph perspective").selectOption("hale");
  const mine = await (await asHale).json();
  const node = mine.nodes.find((n: any) => n.id === `st:${lie.id}`);
  expect(node.stance).toBe(lie.stance);
  expect("grounds" in node).toBe(false);
  await expect(detail.getByTestId("statement-detail")).not.toContainText("had nothing for it");
  // Her own view does carry what she made of it, with its history.
  await expect(detail.getByTestId("statement-stance").locator(".chip")).toHaveCount(lie.stances.length);

  // The other direction: in the speaker's graph the listener's stance is absent,
  // because the listener never told her. The panel must follow the graph, not the observer's union.
  const asIbarra = page.waitForResponse((r) => r.url().includes(`/api/runs/${created.id}/graph`) && r.url().includes("perspective=ibarra"));
  await page.getByLabel("Graph perspective").selectOption("ibarra");
  const hers = await (await asIbarra).json();
  const herNode = hers.nodes.find((n: any) => n.id === `st:${lie.id}`);
  expect("stance" in herNode).toBe(false);
  expect(herNode.grounds).toBe("none");
  await expect(detail.getByTestId("statement-detail")).toContainText("had nothing for it");
  await expect(detail.getByTestId("statement-stance")).toHaveCount(0);
  await expect(detail.getByTestId("statement-stance-hidden")).toBeVisible();
  for (const stance of lie.stances) {
    await expect(detail.getByTestId("statement-detail")).not.toContainText(`${stance.stance} t${stance.tick}`);
  }
  expect(hers.edges.find((e: any) => e.source === `st:${lie.id}` && e.type === "addressed").stance).toBeUndefined();

  // The observer's combined view has both, and going back in time shows the stance as it was then.
  await page.getByLabel("Graph perspective").selectOption("all");
  await expect(detail.getByTestId("statement-stance").locator(".chip")).toHaveCount(lie.stances.length);
  await expect(detail.getByTestId("statement-detail")).toContainText("had nothing for it");
  await page.getByLabel("View tick").focus();
  await page.keyboard.press("Home");
  for (let i = 0; i < lie.stances[0].tick; i++) await page.keyboard.press("ArrowRight"); // no waiting: see slider.spec.ts
  await expect(tickLabel(page)).toContainText(`Tick ${lie.stances[0].tick} of 8`);
  await expect(detail.getByTestId("statement-stance").locator(".chip")).toHaveCount(1);
  await expect(detail.getByTestId("statement-stance")).toContainText(`${lie.stances[0].stance} t${lie.stances[0].tick}`);
  await page.getByRole("button", { name: "Back to latest" }).click();
  await expect(detail.getByTestId("statement-stance").locator(".chip")).toHaveCount(lie.stances.length);

  // The timeline tells it in order.
  await page.getByRole("group", { name: "Timeline filter" }).getByRole("button", { name: "Claims", exact: true }).click();
  const events = await getJson(request, `/api/runs/${created.id}/events`);
  await expect(page.locator(".timeline-panel", { hasText: "Statement" }).locator(".ev-talk", { hasText: `Statement ${lie.id}` })).toHaveCount(1);
  await expect(page.locator(".ev-deception", { hasText: "has caught" })).toHaveCount(events.filter((e: any) => e.type === "CredibilityRevised" && e.data.credibility?.standing === "impeached").length);

  await page.waitForLoadState("networkidle");
  for (const body of bodies) {
    for (const forbidden of ['"culprit"', '"solution"', '"true"', '"agendas"', '"protects"']) {
      expect(body.text.includes(forbidden), `${body.url} contains ${forbidden}`).toBe(false);
    }
  }

  // Closed: the evaluation says which statements were false and who saw through them.
  await page.getByRole("button", { name: "Run to end" }).click();
  await expect(page.locator(".topbar .chip")).toContainText("closed");
  const result = (await getJson(request, `/api/runs/${created.id}/evaluation`)).result;
  const testimony = result.testimony;
  expect(testimony.false.num).toBeGreaterThan(0);
  await mainTab(page, "Evaluation").click();
  const section = page.locator(".evaluation .section").filter({ has: page.locator("h3", { hasText: /^Testimony$/ }) });
  await expect(section.getByTestId("testimony-items").locator("tr")).toHaveCount(testimony.items.length);
  await expect(section.getByTestId("testimony-items").locator(".chip", { hasText: /^false$/ })).toHaveCount(testimony.false.num);
  await expect(section).toContainText(`${testimony.false_accepted_at_close.num}/${testimony.false_accepted_at_close.den}`);
  await expect(section).toContainText(`${testimony.false_speakers_impeached.num}/${testimony.false_speakers_impeached.den}`);
  await expect(page.getByTestId("outcome-category")).toHaveText(`(${result.category.replace("_", ", ")})`);

  // A run with statements in it replays like any other.
  await mainTab(page, "Lab").click();
  await page.getByRole("button", { name: "Verify this run" }).click();
  await expect(page.getByTestId("verify-report").locator("tbody .chip", { hasText: "pass" })).toHaveCount(4);
});
