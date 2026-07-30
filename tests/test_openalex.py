from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neutral_atom_graph.db import LiteratureDB
from neutral_atom_graph.openalex import OpenAlexClient


class OpenAlexClientTests(unittest.TestCase):
    def test_search_removes_pipe_operator_from_physics_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with LiteratureDB(Path(temp) / "test.sqlite") as db:
                client = OpenAlexClient(db)
                with patch.object(
                    client, "get", return_value={"results": []}
                ) as get:
                    client.search_work(
                        "Efficient factories with $|CCZ> to $2|T>$", 2025
                    )
        params = get.call_args.kwargs
        self.assertNotIn("|", params["search"])
        self.assertIn("ccz", params["search"])


if __name__ == "__main__":
    unittest.main()
