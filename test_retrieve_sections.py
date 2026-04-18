from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
RETRIEVE_SECTIONS_PATH = BACKEND_DIR / "retrieve_sections.py"


class RetrieveSectionsTests(unittest.TestCase):
    def run_retrieve_json(self, query: str) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, str(RETRIEVE_SECTIONS_PATH), query, "--json"],
            cwd=BACKEND_DIR,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return json.loads(completed.stdout)

    def run_verify_json(self) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, str(RETRIEVE_SECTIONS_PATH), "--verify", "--json"],
            cwd=BACKEND_DIR,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return json.loads(completed.stdout)

    def test_json_output_contains_default_retrieval_contract(self) -> None:
        payload = self.run_retrieve_json("什么是命题")

        self.assertEqual(payload["query"], "什么是命题")
        self.assertEqual(payload["top_k"], 5)
        self.assertGreaterEqual(len(payload["results"]), 1)

        first_result = payload["results"][0]
        self.assertEqual(first_result["query"], "什么是命题")
        self.assertEqual(first_result["section_id"], "3.2.1")
        self.assertEqual(first_result["title"], "命题")
        self.assertEqual(
            first_result["source_path"],
            "math/离散数学及其应用/笔记/第3章 命题逻辑/3.2 命题与命题联结词/3.2.1 命题.md",
        )
        self.assertEqual(first_result["pdf_page_start"], 67)
        self.assertEqual(first_result["pdf_page_end"], 67)
        self.assertIn("match_reasons", first_result)
        self.assertIn("snippet", first_result)

    def test_verify_json_output_contains_default_verification_contract(self) -> None:
        payload = self.run_verify_json()

        summary = payload["summary"]
        self.assertEqual(summary["case_count"], 11)
        self.assertEqual(summary["top_k"], 5)
        self.assertEqual(summary["top1_hits"], 11)
        self.assertEqual(summary["top3_hits"], 11)
        self.assertEqual(summary["top_k_hits"], 11)

        self.assertEqual(len(payload["cases"]), 11)
        first_case = payload["cases"][0]
        self.assertEqual(first_case["query"], "什么是命题")
        self.assertEqual(first_case["expected_section_id"], "3.2.1")
        self.assertEqual(first_case["matched_rank"], 1)
        self.assertTrue(first_case["top1_hit"])
        self.assertTrue(first_case["top3_hit"])
        self.assertTrue(first_case["top5_hit"])
        self.assertGreaterEqual(len(first_case["results"]), 1)


if __name__ == "__main__":
    unittest.main()
