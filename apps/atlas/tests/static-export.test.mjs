import assert from "node:assert/strict";
import { access, readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import test from "node:test";

const atlasRoot = fileURLToPath(new URL("../", import.meta.url));
const outUrl = new URL("../out/", import.meta.url);
const configuredBasePath = process.env.PAGES_BASE_PATH?.replace(/\/$/, "") ?? "";
const expectedBasePath = configuredBasePath === "/" ? "" : configuredBasePath;

async function assertFile(relativePath) {
  const fileUrl = new URL(relativePath, outUrl);
  await access(fileUrl);
  assert.equal((await stat(fileUrl)).isFile(), true, `${relativePath} should be a file`);
}

test("exports a self-contained literature atlas", async () => {
  await Promise.all([
    assertFile("index.html"),
    assertFile("favicon.svg"),
    assertFile("og.png"),
    assertFile(".nojekyll"),
    assertFile("data/core-graph.json"),
    assertFile("data/full-graph.json"),
  ]);
  assert.equal((await stat(new URL("_next/", outUrl))).isDirectory(), true);

  const html = await readFile(new URL("index.html", outUrl), "utf8");
  assert.match(html, /<title>中性原子量子计算<\/title>/u);
  assert.match(html, new RegExp(`${expectedBasePath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/_next/`));
  if (expectedBasePath) {
    assert.doesNotMatch(html, /(?:href|src)="\/(?:_next|favicon\.svg|og\.png)/u);
    assert.match(html, new RegExp(`${expectedBasePath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/favicon\\.svg`));
  }
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/u);
});

test("ships valid graph data and no legacy worker build", async () => {
  const [packageJson, coreText, fullText] = await Promise.all([
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    readFile(new URL("data/core-graph.json", outUrl), "utf8"),
    readFile(new URL("data/full-graph.json", outUrl), "utf8"),
  ]);
  const pkg = JSON.parse(packageJson);
  const core = JSON.parse(coreText);
  const full = JSON.parse(fullText);

  assert.equal(pkg.scripts.build, "next build");
  assert.equal(pkg.devDependencies?.vinext, undefined);
  assert.equal(pkg.devDependencies?.wrangler, undefined);
  assert.ok(core.meta.nodeCount >= 600);
  assert.ok(full.meta.nodeCount >= 14_000);
  await assert.rejects(access(new URL("../dist/server/index.js", import.meta.url)));
  assert.equal(atlasRoot.endsWith("atlas\\") || atlasRoot.endsWith("atlas/"), true);
});
