import assert from "node:assert/strict";
import test from "node:test";
import { createTemporalCitationLayout } from "../app/temporal-citation-layout.ts";

function placementById(layout) {
  return Object.fromEntries(
    layout.positions.map((position) => [
      position.nodeId,
      {
        year: position.year,
        layerIndex: position.layerIndex,
        order: position.order,
        x: position.x,
        y: position.y,
      },
    ]),
  );
}

function edgesFor(nodes, relations) {
  const indexById = new Map(nodes.map((node, index) => [node.id, index]));
  return relations.map(([citingId, citedId]) => [
    indexById.get(citingId),
    indexById.get(citedId),
  ]);
}

test("lays out calendar-year bands from old to new and keeps unknown years separate", () => {
  const nodes = [
    { id: "old-b", year: 2019 },
    { id: "old-a", year: 2019 },
    { id: "middle", year: 2021 },
    { id: "latest", year: 2024 },
    { id: "unknown", year: null },
  ];
  const edges = [
    [2, 0],
    [2, 1],
    [3, 2],
    [4, 2],
  ];

  const layout = createTemporalCitationLayout(nodes, edges, {
    yearGap: 100,
    nodeGap: 40,
    unknownYearGap: 70,
  });

  assert.deepEqual(layout.yearRange, { min: 2019, max: 2024 });
  assert.deepEqual(
    layout.layers.map(({ year, kind, x }) => ({ year, kind, x })),
    [
      { year: 2019, kind: "year", x: 0 },
      { year: 2021, kind: "year", x: 200 },
      { year: 2024, kind: "year", x: 500 },
      { year: null, kind: "unknown-year", x: 570 },
    ],
  );
  assert.equal(layout.unknownYearLayerIndex, 3);
  assert.equal(layout.positions[0].x, layout.positions[1].x);
  assert.notEqual(layout.positions[0].y, layout.positions[1].y);
  assert.equal(layout.positions[4].layerIndex, 3);
  assert.equal(layout.flowDirection, "older-to-newer");
  assert.equal(layout.edgeContract, "citing-to-cited");
});

test("supports multiple parents, cross-layer citations, and same-year nodes", () => {
  const nodes = [
    { id: "parent-a", year: 2018 },
    { id: "parent-b", year: 2019 },
    { id: "sibling", year: 2022 },
    { id: "child", year: 2022 },
    { id: "descendant", year: 2025 },
  ];
  const edges = [
    [3, 0],
    [3, 1],
    [4, 3],
    [4, 0],
    [3, 2],
  ];

  const layout = createTemporalCitationLayout(nodes, edges);
  const positions = placementById(layout);

  assert.ok(positions["parent-a"].x < positions["parent-b"].x);
  assert.ok(positions["parent-b"].x < positions.child.x);
  assert.ok(positions.child.x < positions.descendant.x);
  assert.equal(positions.child.x, positions.sibling.x);
  assert.notEqual(positions.child.y, positions.sibling.y);
  assert.equal(layout.positions.length, nodes.length);
  assert.equal(
    new Set(layout.layers.flatMap((layer) => layer.nodeIndices)).size,
    nodes.length,
  );
});

test("is deterministic across repeated calls and reordered equivalent input", () => {
  const relations = [
    ["later-a", "root-a"],
    ["later-a", "root-b"],
    ["later-b", "root-b"],
    ["final", "later-a"],
    ["final", "later-b"],
  ];
  const nodes = [
    { id: "root-b", year: 2017 },
    { id: "later-b", year: 2020 },
    { id: "final", year: 2023 },
    { id: "root-a", year: 2017 },
    { id: "later-a", year: 2020 },
  ];
  const reorderedNodes = [
    nodes[4],
    nodes[3],
    nodes[2],
    nodes[1],
    nodes[0],
  ];

  const first = createTemporalCitationLayout(
    nodes,
    edgesFor(nodes, relations),
  );
  const repeated = createTemporalCitationLayout(
    nodes,
    edgesFor(nodes, relations),
  );
  const reordered = createTemporalCitationLayout(
    reorderedNodes,
    edgesFor(reorderedNodes, relations),
  );

  assert.deepEqual(first, repeated);
  assert.deepEqual(placementById(first), placementById(reordered));
});

test("does not mutate inputs and safely ignores malformed edges", () => {
  const nodes = [
    { id: "known", year: 2020 },
    { id: "unknown-b", year: Number.NaN },
    { id: "unknown-a", year: null },
  ];
  const edges = [
    [1, 0],
    [99, 0],
    [-1, 0],
    [0, 0],
  ];
  const originalNodes = nodes.map((node) => ({ ...node }));
  const originalEdges = edges.map((edge) => [...edge]);

  const layout = createTemporalCitationLayout(nodes, edges, { sweeps: 99 });

  assert.deepEqual(nodes, originalNodes);
  assert.deepEqual(edges, originalEdges);
  assert.equal(layout.layers.at(-1).kind, "unknown-year");
  assert.deepEqual(
    layout.layers.at(-1).nodeIndices.map((index) => nodes[index].id),
    ["unknown-a", "unknown-b"],
  );
  assert.equal(layout.axis.yearGap, 180);
});

test("handles an empty graph and an all-unknown graph", () => {
  const empty = createTemporalCitationLayout([], []);
  assert.deepEqual(empty.layers, []);
  assert.deepEqual(empty.positions, []);
  assert.equal(empty.yearRange, null);
  assert.deepEqual(empty.bounds, {
    minX: 0,
    maxX: 0,
    minY: 0,
    maxY: 0,
    width: 0,
    height: 0,
  });

  const unknown = createTemporalCitationLayout(
    [
      { id: "b", year: null },
      { id: "a", year: null },
    ],
    [],
    { nodeGap: 20 },
  );
  assert.equal(unknown.layers.length, 1);
  assert.equal(unknown.layers[0].x, 0);
  assert.equal(unknown.layers[0].kind, "unknown-year");
  assert.deepEqual(
    unknown.layers[0].nodeIndices.map(
      (nodeIndex) => unknown.positions[nodeIndex].nodeId,
    ),
    ["a", "b"],
  );
  assert.deepEqual(
    unknown.positions.map(({ y }) => y).sort((left, right) => left - right),
    [-10, 10],
  );
});
