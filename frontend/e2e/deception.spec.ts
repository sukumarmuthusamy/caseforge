import { expect, test } from "@playwright/test";
import { agentCard, currentRunId, getJson, getRun, mainTab, tickLabel } from "./helpers";

test("a deceptive technician: behaviour is visible, motive stays hidden until the reveal, the cost is measured", async ({ page, request }) => {
  const bodies: { url: string; text: string }[] = [];
  // Only what the browser fetches once this run exists is checked. The page may first have opened a
  // run that an earlier test left closed, whose evaluation legitimately carries the agendas.
  let collecting = false;
  page.on("response", async (response) => {
    if (!collecting || !response.url().includes("/api/")) return;
    try {
      bodies.push({ url: response.url(), text: await response.text() });
    } catch {
      // nothing to inspect
    }
  });

  // Assign the policy through the interface.
  await page.goto("/");
  const chooser = page.getByRole("button", { name: "Choose seed and policies..." });
  const newRun = page.getByRole("button", { name: "New run" });
  await expect(chooser.or(newRun)).toBeVisible();
  await ((await chooser.isVisible()) ? chooser : newRun).click();
  const dialog = page.getByRole("dialog", { name: "New investigation" });
  await dialog.getByLabel("Seed").fill("7");
  await dialog.locator(".policy-row", { hasText: "Jonah Reyes" }).locator("select").selectOption("deceptive");
  await dialog.getByRole("button", { name: "Open the case" }).click();
  await expect(tickLabel(page)).toContainText("Tick 0 of 0");
  const id = await currentRunId(page);
  collecting = true;
  expect((await getRun(request, id)).policies.reyes).toBe("deceptive");
  await expect(agentCard(page, "Jonah Reyes")).toContainText("deceptive");

  // Advance until the first record has been held back.
  let withheld: any[] = [];
  for (let step = 0; step < 6 && withheld.length === 0; step++) {
    const before = (await getRun(request, id)).tick;
    await page.locator(".transport").getByRole("button", { name: "+5", exact: true }).click();
    await expect(tickLabel(page)).toContainText(`Tick ${before + 5} of ${before + 5}`);
    withheld = (await getJson(request, `/api/runs/${id}/snapshot`)).requests.filter((r: any) => r.withheld.length > 0);
  }
  expect(withheld.length).toBeGreaterThan(0);
  expect((await getRun(request, id)).status).toBe("running");

  // The observer sees what he did ...
  await agentCard(page, "Jonah Reyes").click();
  const panel = page.locator(".agent-panel");
  await panel.getByRole("tab", { name: /^Requests/ }).click();
  await expect(panel.getByTestId("withheld")).toHaveCount(withheld.length);
  await expect(panel.getByTestId("withheld").first()).toContainText("Held back by Jonah Reyes");
  await page.getByRole("group", { name: "Timeline filter" }).getByRole("button", { name: "Evidence", exact: true }).click();
  await expect(page.locator(".ev-deception", { hasText: "holds back" })).toHaveCount(withheld.length);

  // ... but not why: the agenda is scenario-private until the solution is shown.
  await expect(page.getByTestId("agenda")).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  for (const body of bodies) {
    for (const forbidden of ['"agendas"', '"protects"', '"deflects_to"', '"solution"', '"culprit"']) {
      expect(body.text.includes(forbidden), `${body.url} contains ${forbidden}`).toBe(false);
    }
  }

  // Run to the end and read the measured cost.
  await page.getByRole("button", { name: "Run to end" }).click();
  await expect(page.locator(".topbar .chip")).toContainText("closed");
  const evaluation = (await getJson(request, `/api/runs/${id}/evaluation`)).result;
  const deception = evaluation.deception;
  expect(deception.answers_with_withholding).toBeGreaterThan(0);

  await mainTab(page, "Evaluation").click();
  const section = page.locator(".evaluation .section", { hasText: "Deception" });
  await expect(section.getByTestId("deception-items").locator("tr")).toHaveCount(deception.items.length);
  await expect(section.getByTestId("deception-agenda")).toContainText("Jonah Reyes was covering for Sam Whitlock");
  await expect(section).toContainText(`${deception.noticed.num}/${deception.noticed.den}`);
  await expect(section.locator(".chip", { hasText: "noticed t" })).toHaveCount(deception.items.filter((i: any) => i.noticed_tick !== null).length);

  // The agenda and the detective's discovery are now on the agents' panels.
  await agentCard(page, "Jonah Reyes").click();
  await expect(page.getByTestId("agenda")).toContainText("Keeps Sam Whitlock out of the record");
  await expect(page.getByTestId("agenda")).toContainText("This agent is acting on it.");
  const okafor = (await getJson(request, `/api/runs/${id}/snapshot`)).agents.find((a: any) => a.id === "okafor");
  await agentCard(page, "Det. Mara Okafor").click();
  if (okafor.discrepancies.length > 0) {
    await expect(page.getByTestId("discrepancies").locator("div", { hasText: "left out" })).toHaveCount(okafor.discrepancies.length);
  } else {
    await expect(page.getByTestId("discrepancies")).toHaveCount(0);
  }

  // A run with deception in it replays like any other.
  await mainTab(page, "Lab").click();
  await page.getByRole("button", { name: "Verify this run" }).click();
  await expect(page.getByTestId("verify-report").locator("tbody .chip", { hasText: "pass" })).toHaveCount(4);
});
