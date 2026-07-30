import assert from "node:assert/strict";
import test from "node:test";
import {
  arrowheadPoints,
  citationDirectionForFocus,
  orientedCitationEdge,
} from "../app/citation-direction.ts";

test("citation direction is relative to the focused paper", () => {
  assert.equal(citationDirectionForFocus(4, 9, 4), "outgoing");
  assert.equal(citationDirectionForFocus(4, 9, 9), "incoming");
  assert.equal(citationDirectionForFocus(4, 9, 2), null);
});

test("citation and development views use explicit opposite visual flows", () => {
  assert.deepEqual(orientedCitationEdge(4, 9, "citation"), {
    from: 4,
    to: 9,
  });
  assert.deepEqual(orientedCitationEdge(4, 9, "development"), {
    from: 9,
    to: 4,
  });
});

test("arrowhead points toward the cited target", () => {
  const points = arrowheadPoints(
    { x: 0, y: 0 },
    { x: 20, y: 0 },
    { inset: 2, length: 6, halfWidth: 3 },
  );
  assert.deepEqual(points, [
    { x: 18, y: 0 },
    { x: 12, y: 3 },
    { x: 12, y: -3 },
  ]);
  assert.equal(arrowheadPoints({ x: 1, y: 1 }, { x: 1, y: 1 }), null);
});
