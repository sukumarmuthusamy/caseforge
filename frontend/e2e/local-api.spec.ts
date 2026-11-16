import { chromium, expect, test } from "@playwright/test";
import { createRun, getJson } from "./helpers";

// The API is a local tool with no accounts. These tests drive a real browser at the real server
// and watch what the server answers, because the protections (a Host allow-list and a cross-site check on
// state changes) are only worth anything if an actual browser request is turned away before it acts.

const ATTACKER = "http://attacker.test";

// Current Chromium builds already refuse a request from a public web page to a loopback address (Private
// Network Access / Local Network Access): that is a mitigation outside this application, and it is not
// universal (other browsers, older versions, secure-context permission prompts). To test what CaseForge
// itself does when such a request does arrive, this one test starts its own browser with that protection
// switched off, so the request reaches the server and the server's answer is what is checked.
const WITHOUT_BROWSER_PROTECTION = [
  "--disable-features=LocalNetworkAccessChecks,PrivateNetworkAccessRespectPreflightResults,BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessSendPreflights,LocalNetworkAccessChecksWarn",
];
const channel = process.env.CASEFORGE_E2E_BROWSER ?? (process.platform === "win32" ? "msedge" : "chrome");

function origin(testInfo: { project: { use: { baseURL?: string } } }) {
  return new URL(testInfo.project.use.baseURL!);
}

test("another website cannot change anything through the loopback address", async ({ request }, testInfo) => {
  const browser = await chromium.launch({ channel: channel === "chromium" ? undefined : channel, args: WITHOUT_BROWSER_PROTECTION });
  const page = await browser.newPage();
  try {
    await crossSiteAttempt(page, request, testInfo);
  } finally {
    await browser.close();
  }
});

async function crossSiteAttempt(page: import("@playwright/test").Page, request: import("@playwright/test").APIRequestContext, testInfo: Parameters<typeof origin>[0] & import("@playwright/test").TestInfo) {
  const base = origin(testInfo);
  const target = createRun(request, { label: "e2e cross-site target" });
  const run = await target;
  const runsBefore = ((await getJson(request, "/api/runs")) as any[]).map((r) => r.id).sort();

  await page.route(`${ATTACKER}/**`, (route) => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>elsewhere</title><p>an unrelated site</p>" }));
  await page.goto(`${ATTACKER}/`);

  const answers: { method: string; path: string; status: number }[] = [];
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.host === base.host) answers.push({ method: response.request().method(), path: url.pathname, status: response.status() });
  });

  const api = `${base.origin}/api`;
  await page.evaluate(
    async ({ api, id }) => {
      // A script can send a body with no content type and no preflight; a form can post without any body at all.
      await fetch(`${api}/runs`, { method: "POST", mode: "no-cors", body: new Blob(['{"scenario_id":"missing_prototype","seed":9}']) }).catch(() => undefined);
      await fetch(`${api}/runs`, { method: "POST", mode: "no-cors", headers: { "Content-Type": "text/plain" }, body: '{"seed":9}' }).catch(() => undefined);
      await fetch(`${api}/lab/challenges/control/open`, { method: "POST", mode: "no-cors", body: new Blob(['{"seed":0}']) }).catch(() => undefined);
      // DELETE is not allowed in no-cors mode at all, so it is sent as an ordinary CORS request. The browser sends a
      // preflight first; whether it stops there or the request reaches the server, the run must survive (checked below).
      await fetch(`${api}/runs/${id}`, { method: "DELETE" }).catch(() => undefined);
      await new Promise<void>((resolve) => {
        const frame = document.createElement("iframe");
        frame.name = "sink";
        document.body.append(frame);
        const form = document.createElement("form");
        Object.assign(form, { method: "POST", action: `${api}/runs/${id}/reveal`, target: "sink" });
        document.body.append(form);
        frame.addEventListener("load", () => resolve(), { once: true });
        form.submit();
        setTimeout(resolve, 2000);
      });
      // A read is allowed to go out; the browser must not hand the answer to this page.
      const read = await fetch(`${api}/runs`).then((r) => r.text(), () => "blocked by the browser");
      return read;
    },
    { api, id: run.id },
  ).then((read) => expect(read).toBe("blocked by the browser"));

  // The server saw cross-site posts, and turned each one away. If the browser still stopped every request
  // before it left (a newer build whose protection these flags no longer switch off), there is nothing to
  // observe here: say so loudly instead of passing. The server-side check is also pinned by pytest.
  const posts = answers.filter((a) => a.method === "POST");
  if (posts.length === 0) {
    testInfo.annotations.push({ type: "skipped-reason", description: "the browser blocked every cross-site request itself; the server's answer was not exercised" });
    test.skip(true, "the browser blocked every cross-site request itself; see backend/tests/test_netguard.py for the server-side check");
  }
  expect(posts.length).toBeGreaterThanOrEqual(3);
  expect(posts.map((a) => a.status)).toEqual(posts.map(() => 403));
  // A page is not reliably told whether its cross-site DELETE was stopped at the preflight or reached the server, so
  // its absence here proves nothing. What is asserted: any answer the page did see is a refusal, and the run still
  // exists. The server's 403 for a cross-site DELETE is pinned in backend/tests/test_netguard.py.
  expect(answers.filter((a) => a.method === "DELETE" && a.status !== 403)).toEqual([]);

  // Nothing changed.
  expect(((await getJson(request, "/api/runs")) as any[]).map((r) => r.id).sort()).toEqual(runsBefore);
  expect((await getJson(request, `/api/runs/${run.id}`)).revealed).toBe(false);
}

test("the interface works under either loopback name, and a foreign Host name is refused", async ({ page, request }, testInfo) => {
  const base = origin(testInfo);
  for (const name of ["localhost", "127.0.0.1"]) {
    await page.goto(`http://${name}:${base.port}/#lab`);
    await expect(page.getByTestId("lab-overview")).toBeVisible();
    // The page's own state-changing request carries its own Origin, which is allowed.
    const status = await page.evaluate(async () => (await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario_id: "missing_prototype", seed: 1, label: "e2e own origin" }) })).status);
    expect(status).toBe(201);
  }

  const refused = await request.get("/api/runs", { headers: { Host: `attacker.example:${base.port}` } });
  expect(refused.status()).toBe(400);
  expect((await refused.json()).detail).toContain("Invalid Host header");
});
