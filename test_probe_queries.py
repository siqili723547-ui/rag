from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
PROBE_QUERIES_PATH = BACKEND_DIR / "probe_queries.ps1"


class ProbeQueriesTests(unittest.TestCase):
    def run_probe_json(self, *query: str) -> dict[str, object]:
        completed = subprocess.run(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(PROBE_QUERIES_PATH),
                *query,
                "-Json",
            ],
            cwd=BACKEND_DIR,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return json.loads(completed.stdout)

    def test_json_output_contains_default_probe_contract(self) -> None:
        payload = self.run_probe_json("什么是命题")

        self.assertEqual(payload["backend_dir"], str(BACKEND_DIR))
        self.assertEqual(payload["overall_status"], "ok")
        self.assertEqual(len(payload["probes"]), 1)

        probe = payload["probes"][0]
        self.assertEqual(probe["query"], "什么是命题")
        self.assertEqual(probe["status"], "ok")
        self.assertEqual(probe["top_k"], 5)
        self.assertGreaterEqual(len(probe["results"]), 1)

        first_result = probe["results"][0]
        self.assertEqual(first_result["query"], "什么是命题")
        self.assertIn("section_id", first_result)
        self.assertIn("title", first_result)
        self.assertIn("source_path", first_result)
        self.assertIn("pdf_page_start", first_result)
        self.assertIn("pdf_page_end", first_result)
        self.assertIn("match_reasons", first_result)
        self.assertIn("snippet", first_result)


if __name__ == "__main__":
    unittest.main()
