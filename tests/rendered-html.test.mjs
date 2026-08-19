import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import test from "node:test";

const root = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const nextBin = path.join(root, "node_modules", "next", "dist", "bin", "next");
const port = 3217;

async function waitForServer(child) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`next start exited early with code ${child.exitCode}`);
    try {
      const response = await fetch(`http://127.0.0.1:${port}/dashboard`);
      if (response.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Timed out waiting for next start");
}

async function withServer(run) {
  const child = spawn(process.execPath, [nextBin, "start", "-H", "127.0.0.1", "-p", String(port)], {
    cwd: root,
    env: { ...process.env, CONTROL_API_URL: "http://127.0.0.1:59999", NODE_ENV: "production" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let logs = "";
  child.stdout.on("data", (chunk) => { logs += chunk; });
  child.stderr.on("data", (chunk) => { logs += chunk; });
  try {
    await waitForServer(child);
    await run();
  } catch (error) {
    throw new Error(`${error instanceof Error ? error.message : String(error)}\nNext output:\n${logs}`);
  } finally {
    child.kill();
  }
}

test("renders every primary Windows/Node production workspace", async () => {
  await withServer(async () => {
    const routes = [
      ["/", "Mobile Market Intelligence"],
      ["/dashboard", "Mobile Market Intelligence"],
      ["/scrapers/gsmarena", "Scrapers"],
      ["/admin", "Production operations"],
      ["/database", "Database view"],
      ["/realtime", "Live production status"],
    ];

    for (const [route, heading] of routes) {
      const response = await fetch(`http://127.0.0.1:${port}${route}`);
      assert.equal(response.status, 200, `${route} should render`);
      assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
      assert.match(await response.text(), new RegExp(heading, "i"));
    }
  });
});
