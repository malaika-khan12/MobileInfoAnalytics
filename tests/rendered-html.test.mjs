import assert from "node:assert/strict";
import test from "node:test";

async function loadWorker() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker;
}

async function requestPage(worker, path) {
  return worker.fetch(
    new Request(`http://localhost${path}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("renders every primary production workspace", async () => {
  const worker = await loadWorker();
  const routes = [
    ["/", "Mobile Analytics dashboard"],
    ["/dashboard", "Mobile Analytics dashboard"],
    ["/scrapers/gsmarena", "Scrapers"],
    ["/admin", "Production operations"],
    ["/database", "Database view"],
    ["/realtime", "Live production status"],
  ];

  for (const [path, heading] of routes) {
    const response = await requestPage(worker, path);
    assert.equal(response.status, 200, `${path} should render`);
    assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
    assert.match(await response.text(), new RegExp(heading, "i"));
  }
});
