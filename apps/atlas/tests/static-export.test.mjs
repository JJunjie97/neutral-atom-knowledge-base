import assert from "node:assert/strict";
import { access, readFile, readdir, stat } from "node:fs/promises";
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

function findForbiddenPublicationField(value) {
  if (Array.isArray(value)) {
    return value.map(findForbiddenPublicationField).find(Boolean) ?? null;
  }
  if (!value || typeof value !== "object") return null;
  for (const [key, child] of Object.entries(value)) {
    if (["abstract", "context", "excerpt", "full_text", "fulltext"].includes(key)) {
      return key;
    }
    const nested = findForbiddenPublicationField(child);
    if (nested) return nested;
  }
  return null;
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
  assert.equal(typeof core.taxonomy?.version, "string");
  assert.ok(core.taxonomy.dimensions.length >= 17);
  assert.ok(Object.keys(core.meta.facetCounts?.atomic_element ?? {}).length >= 4);
  assert.ok(core.nodes.some((node) => Object.keys(node.facets ?? {}).length > 0));
  assert.ok(full.nodes.some((node) => Object.keys(node.facets ?? {}).length > 0));

  const classifiedSeed = core.nodes.find((node) => node.classificationPath);
  assert.ok(classifiedSeed, "a seed paper should expose classification evidence");
  const classificationRelativePath = classifiedSeed.classificationPath.replace(
    /^\//,
    "",
  );
  await assertFile(classificationRelativePath);
  const classificationText = await readFile(
    new URL(classificationRelativePath, outUrl),
    "utf8",
  );
  const classification = JSON.parse(classificationText);
  assert.equal(classification.taxonomyVersion, core.taxonomy.version);
  assert.ok(Array.isArray(classification.classifications));
  assert.equal("abstract" in classification, false);
  assert.doesNotMatch(classificationText, /context_text/i);

  await assert.rejects(access(new URL("../dist/server/index.js", import.meta.url)));
  assert.equal(atlasRoot.endsWith("atlas\\") || atlasRoot.endsWith("atlas/"), true);
});

test("ships a consistent multi-dimensional taxonomy without embedding evidence", async () => {
  const [coreText, fullText] = await Promise.all([
    readFile(new URL("data/core-graph.json", outUrl), "utf8"),
    readFile(new URL("data/full-graph.json", outUrl), "utf8"),
  ]);
  const core = JSON.parse(coreText);
  const full = JSON.parse(fullText);

  for (const graph of [core, full]) {
    assert.equal(typeof graph.taxonomy, "object");
    assert.ok(Array.isArray(graph.taxonomy.dimensions));
    assert.ok(graph.taxonomy.dimensions.length >= 8);
    assert.equal(typeof graph.meta.facetCounts, "object");

    const categoriesByDimension = new Map(
      graph.taxonomy.dimensions.map((dimension) => [
        dimension.id,
        new Set(dimension.categories.map((category) => category.id)),
      ]),
    );
    const computedCounts = {};
    for (const node of graph.nodes) {
      assert.equal(typeof node.facets, "object");
      assert.equal(typeof node.layoutGroup, "string");
      assert.equal("classification_evidence" in node, false);
      assert.equal("classifications" in node, false);
      for (const [dimensionId, categoryIds] of Object.entries(node.facets)) {
        assert.ok(categoriesByDimension.has(dimensionId), dimensionId);
        computedCounts[dimensionId] ??= {};
        for (const categoryId of new Set(categoryIds)) {
          assert.ok(
            categoriesByDimension.get(dimensionId).has(categoryId),
            `${dimensionId}:${categoryId}`,
          );
          computedCounts[dimensionId][categoryId] =
            (computedCounts[dimensionId][categoryId] ?? 0) + 1;
        }
      }
    }
    assert.deepEqual(graph.meta.facetCounts, computedCounts);
  }

  const seedPaths = core.nodes
    .filter((node) => node.seed)
    .map((node) => node.classificationPath);
  assert.equal(seedPaths.every(Boolean), true);
  assert.equal(new Set(seedPaths).size, core.meta.seedCount);

  const classificationFiles = (await readdir(new URL("data/classifications/", outUrl)))
    .filter((name) => name.endsWith(".json"));
  assert.equal(classificationFiles.length, core.meta.seedCount);

  const publicShards = await Promise.all(
    classificationFiles.map(async (name) =>
      JSON.parse(
        await readFile(new URL(`data/classifications/${name}`, outUrl), "utf8"),
      ),
    ),
  );
  for (const shard of publicShards) {
    assert.equal(shard.taxonomyVersion, core.taxonomy.version);
    assert.equal(typeof shard.facets, "object");
    assert.ok(Array.isArray(shard.classifications));
    assert.equal(findForbiddenPublicationField(shard), null);
  }
  assert.ok(publicShards.some((shard) => shard.classifications.length > 0));
});
