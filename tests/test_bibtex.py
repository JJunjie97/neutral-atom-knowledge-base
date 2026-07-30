from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from neutral_atom_graph.bibtex import (
    extract_arxiv_id,
    extract_doi,
    normalize_title,
    parse_bibtex,
    scan_tex_citations,
)


SAMPLE = r"""
% a comment
@article{multi,
  author = {de L\'es\'eleuc, Sylvain and Doe, Jane},
  title = {A {Nested} {Rydberg}-Atom Title},
  year = {2024},
  doi = {https://doi.org/10.1234/ABC.42}
}
@article{quoted,
  author = "Jacob, Abraham and Browne, Dan E.",
  title = "{Single-Shot Decoding}",
  eprint = "2508.08191",
  archivePrefix = "arXiv",
  month = Aug,
  year = "2025"
}
@article{singleline, title={One line}, DOI={10.5555/X.Y}, year={2018}, month=Sept}
"""


class BibTeXTests(unittest.TestCase):
    def test_mixed_value_styles_and_nested_braces(self) -> None:
        entries = parse_bibtex(SAMPLE)
        self.assertEqual([entry.key for entry in entries], ["multi", "quoted", "singleline"])
        self.assertEqual(entries[0].fields["title"], "A {Nested} {Rydberg}-Atom Title")
        self.assertEqual(entries[1].fields["month"], "Aug")
        self.assertEqual(entries[2].fields["year"], "2018")

    def test_identifier_extraction(self) -> None:
        entries = parse_bibtex(SAMPLE)
        self.assertEqual(extract_doi(entries[0]), "10.1234/abc.42")
        self.assertEqual(extract_arxiv_id(entries[1]), "2508.08191")

    def test_title_normalization(self) -> None:
        self.assertEqual(
            normalize_title(r"High-Fidelity {Rydberg}-Atom Qubits"),
            "high fidelity rydberg atom qubits",
        )

    def test_tex_citation_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.tex").write_text(
                r"\cite{multi, quoted} and \citep[see][]{singleline}",
                encoding="utf-8",
            )
            citations = scan_tex_citations(root)
        self.assertEqual(citations["multi"], ["a.tex"])
        self.assertEqual(citations["quoted"], ["a.tex"])
        self.assertEqual(citations["singleline"], ["a.tex"])


if __name__ == "__main__":
    unittest.main()
