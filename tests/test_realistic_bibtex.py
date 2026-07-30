from __future__ import annotations

import unittest

from neutral_atom_graph.bibtex import parse_bibtex


class RealisticBibTeXTests(unittest.TestCase):
    def test_latex_quote_accent_inside_braced_author(self) -> None:
        entries = parse_bibtex(
            """
            @article{accent,
              author={Leclerc, Lucas and Henriet, Lo{"i}c},
              title={A title},
              year={2026}
            }
            @article{next, title={The next entry}, year={2025}}
            """
        )
        self.assertEqual([entry.key for entry in entries], ["accent", "next"])


if __name__ == "__main__":
    unittest.main()
