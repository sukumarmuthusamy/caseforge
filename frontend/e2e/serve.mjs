// Starts the real CaseForge server for the browser tests: the built UI, a fresh
// throwaway database, and model-backed policies switched off.
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..");
const port = process.env.CASEFORGE_E2E_PORT ?? "8791";

const venvPython = path.join(root, "backend", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const python = process.env.CASEFORGE_PYTHON ?? venvPython;
if (!process.env.CASEFORGE_PYTHON && !existsSync(venvPython)) {
  console.error(`No Python environment at ${venvPython}. Create it (see README) or set CASEFORGE_PYTHON.`);
  process.exit(1);
}

const dist = path.join(root, "frontend", "dist");
if (!existsSync(path.join(dist, "index.html"))) {
  console.error("frontend/dist is missing. Run `npm run build` first, or use `npm run e2e`, which builds.");
  process.exit(1);
}

const scratch = mkdtempSync(path.join(os.tmpdir(), "caseforge-e2e-"));
const database = path.join(scratch, "e2e.sqlite3");
const seeded = spawnSync(python, [path.join(here, "seed_readonly.py"), database], {
  cwd: path.join(root, "backend"),
  stdio: "inherit",
  env: { ...process.env, CASEFORGE_LLM_ENABLED: "0", PYTHONDONTWRITEBYTECODE: "1" },
});
if (seeded.status !== 0) {
  console.error("Could not seed the read-only run for the browser tests.");
  process.exit(1);
}
const child = spawn(python, ["-m", "caseforge", "serve", "--port", port, "--db", database], {
  cwd: path.join(root, "backend"),
  stdio: "inherit",
  env: { ...process.env, CASEFORGE_LLM_ENABLED: "0", CASEFORGE_FRONTEND_DIST: dist, PYTHONDONTWRITEBYTECODE: "1" },
});

const stop = () => child.kill();
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
child.on("exit", (code) => {
  try {
    rmSync(scratch, { recursive: true, force: true });
  } catch {
    // The database lives in the system temp directory; leaving it behind is harmless.
  }
  process.exit(code ?? 0);
});
