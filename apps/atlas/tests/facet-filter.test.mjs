import assert from "node:assert/strict";
import test from "node:test";
import { matchesFacetSelections } from "../app/graph-utils.ts";

const node = {
  facets: {
    atomic_element: ["rubidium", "cesium"],
    computing_mode: ["digital_gate_model"],
    networking: ["atom_photon_entanglement"],
  },
};

test("facet selections use OR within one dimension", () => {
  assert.equal(
    matchesFacetSelections(node, {
      atomic_element: ["strontium", "rubidium"],
    }),
    true,
  );
  assert.equal(
    matchesFacetSelections(node, {
      atomic_element: ["strontium", "ytterbium"],
    }),
    false,
  );
});

test("facet selections use AND across dimensions", () => {
  assert.equal(
    matchesFacetSelections(node, {
      atomic_element: ["cesium"],
      computing_mode: ["digital_gate_model", "analog_simulation"],
    }),
    true,
  );
  assert.equal(
    matchesFacetSelections(node, {
      atomic_element: ["cesium"],
      computing_mode: ["analog_simulation"],
    }),
    false,
  );
});

test("empty selections do not exclude a node", () => {
  assert.equal(matchesFacetSelections(node, {}), true);
  assert.equal(matchesFacetSelections(node, { networking: [] }), true);
});