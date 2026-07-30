# Neutral-atom taxonomy

`neutral_atom_taxonomy.json` is the curated, deterministic taxonomy used to
build auditable facets for the neutral-atom literature graph. It is grounded in
the section hierarchy and citation contexts of *Strategic Plan for Neutral Atom
Quantum Computation* (`arXiv:2607.21554`) and is designed to remain useful when
full abstracts and Markdown papers are added later.

## Design principles

- **Multi-dimensional and multi-label.** A paper can simultaneously concern
  rubidium-87, a hyperfine encoding, an optical-tweezer array, Rydberg-blockade
  gates, loss-aware QEC, and compilation.
- **Broad section labels are separate from detailed technical labels.**
  `review_domain` is the only dimension whose rules use top-level review
  sections. Detailed categories require evidence in a title, abstract, OpenAlex
  topic, or local citation context. Citing a paper in a hardware chapter does
  not automatically make it a paper about every technology discussed there.
- **Rules favor precision over recall.** The initial taxonomy intentionally
  leaves some papers unclassified instead of assigning plausible but
  unsupported labels.
- **Every assignment remains auditable.** The classifier stores rule IDs,
  matched text signals, and review mention IDs.
- **Publication venue is metadata, not a topic.** The project derives a venue
  facet separately. The low `venue` field weight prevents a journal name from
  dominating a technical classification.

## Dimensions

The curated dimensions cover:

- review domain;
- element and isotope;
- physical platform;
- qubit encoding and array architecture;
- computing mode, interactions, gates, control, loading, readout, and noise;
- QEC code families, QEC techniques, and decoders;
- compilation stages;
- integrated photonics;
- networking;
- scientific and computational applications.

All labels have stable English IDs and English/Chinese display names.

## Important false-positive guards

### Rydberg is not automatically a qubit encoding

Generic phrases such as “Rydberg excitation”, “Rydberg interaction”, or
“Rydberg blockade” are classified under control or interaction dimensions.
`qubit_encoding/explicit_rydberg_state` requires explicit language such as
“Rydberg-state qubit” or “qubit encoded in a Rydberg state”. Circular Rydberg
states have their own explicit category.

### Lithium photonic materials are not lithium atoms

The element vocabulary deliberately starts with the four atomic elements
explicitly central to the review: Rb, Cs, Sr, and Yb. “Lithium niobate” and
“lithium tantalate” are classified only as TFLN/TFLT photonic materials. Do not
add an atomic-lithium rule using the bare word `lithium`; a future Li-atom rule
must require atomic context or an isotope such as `6Li` or `7Li`.

### Trapped ions and neutral atoms remain distinct

`physical_platform` rules use only titles, abstracts, and provider topics. They
do not use review citation context, because the networking and QEC chapters
compare neutral atoms with Ca+, Ba+, Cd+, Yb+, and other platforms. Element and
isotope facets are independent of platform, so a Yb+ paper may correctly carry
both `atomic_element/ytterbium` and `physical_platform/trapped_ion`.

## Rule semantics and confidence

The file is compatible with
`src/neutral_atom_graph/classification.py`. Rules live below their category and
support:

- `fields`: `title`, `abstract`, `topics`, `venue`, `work_type`,
  `review_context`, or `review_section`;
- `keywords`: case-insensitive whole-token or phrase matching;
- `regex`: Python regular expressions compiled with `re.IGNORECASE`;
- `sections` and `venues`;
- `match`: `any` or `all`;
- `confidence`: the rule-level upper bound.

Effective confidence is capped by the strongest matched field weight. Current
weights express this evidence order:

1. local review citation context;
2. exact top-level review section for broad domain only;
3. title;
4. abstract;
5. OpenAlex topics;
6. work type and venue.

`match: "all"` means every listed keyword/regex criterion must be found among
the selected fields. Prefer one precise regex over a long list of generic words.

## Validate and apply

From the repository root:

```powershell
$env:PYTHONPATH = "src"
python -c "from neutral_atom_graph.classification import load_taxonomy; t=load_taxonomy('taxonomy/neutral_atom_taxonomy.json'); print(t.version, len(t.dimensions), len(t.rules))"
```

Classify the bibliography seed works while synchronizing review citation
contexts:

```powershell
$env:PYTHONPATH = "src"
python -m neutral_atom_graph classify `
  --taxonomy taxonomy/neutral_atom_taxonomy.json `
  --seed-only
```

Omit `--seed-only` to apply metadata rules to every graph node. Nodes without
enough metadata may remain unclassified until abstracts or local Markdown are
available.

## Maintenance

1. Add categories only when they represent a reusable facet rather than a
   one-paper phrase.
2. Add a narrow text rule and test likely counterexamples.
3. Keep review-section rules in `review_domain`; use citation context for
   detailed technology.
4. Never use venue alone to infer a scientific topic.
5. Preserve category IDs once published. Labels and descriptions may improve,
   but changing an ID breaks saved filters and external references.
6. Any content change requires a new `version`. The database rejects a changed
   taxonomy digest under an already registered version.
7. Validate JSON parsing and `load_taxonomy()` before running classification.
