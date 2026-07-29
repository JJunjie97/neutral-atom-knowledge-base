import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the literature atlas shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>中性原子量子计算 · 文献星图<\/title>/i);
  assert.match(html, /正在装载中性原子文献宇宙/);
  assert.doesNotMatch(html, /codex-preview/);
  assert.doesNotMatch(html, /Your site is taking shape/);
});

test("ships both graph tiers and removes the starter preview", async () => {
  const [page, layout, packageJson, coreData, fullData] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    readFile(new URL("../public/data/core-graph.json", import.meta.url), "utf8"),
    readFile(new URL("../public/data/full-graph.json", import.meta.url), "utf8"),
  ]);

  assert.match(page, /LiteratureExplorer/);
  assert.match(layout, /lang="zh-CN"/);
  assert.match(packageJson, /neutral-atom-literature-atlas/);
  assert.equal(JSON.parse(coreData).meta.nodeCount, 637);
  assert.equal(JSON.parse(fullData).meta.nodeCount, 14072);
  await assert.rejects(access(new URL("../app/_sites-preview/", import.meta.url)));
});
