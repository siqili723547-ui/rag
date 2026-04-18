from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
RUN_EVAL_SUITE_PATH = BACKEND_DIR / "run_eval_suite.ps1"
EXPECTED_SUITES = [
    {
        "name": "main_fixed",
        "case_count": 11,
        "top_k": 3,
        "top1": "11/11",
        "top3": "11/11",
        "topk": "11/11",
    },
    {
        "name": "definition_content_head",
        "case_count": 5,
        "top_k": 3,
        "top1": "5/5",
        "top3": "5/5",
        "topk": "5/5",
    },
    {
        "name": "single_char_definition_boundary",
        "case_count": 12,
        "top_k": 5,
        "top1": "12/12",
        "top3": "12/12",
        "topk": "12/12",
    },
    {
        "name": "multi_char_partial_overlap_boundary",
        "case_count": 7,
        "top_k": 3,
        "top1": "7/7",
        "top3": "7/7",
        "topk": "7/7",
    },
    {
        "name": "opening_definition_bridge_boundary",
        "case_count": 4,
        "top_k": 3,
        "top1": "4/4",
        "top3": "4/4",
        "topk": "4/4",
    },
    {
        "name": "concept_family_competition_boundary",
        "case_count": 1,
        "top_k": 5,
        "top1": "1/1",
        "top3": "1/1",
        "topk": "1/1",
    },
    {
        "name": "pure_partial_overlap_residual_boundary",
        "case_count": 2,
        "top_k": 5,
        "top1": "2/2",
        "top3": "2/2",
        "topk": "2/2",
    },
]


class RunEvalSuiteTests(unittest.TestCase):
    def run_eval_suite_json(self) -> dict[str, object]:
        completed = subprocess.run(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(RUN_EVAL_SUITE_PATH),
                "-Json",
            ],
            cwd=BACKEND_DIR,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return json.loads(completed.stdout)

    def test_json_output_contains_default_fixed_eval_contract(self) -> None:
        payload = self.run_eval_suite_json()

        self.assertEqual(payload["backend_dir"], str(BACKEND_DIR))
        self.assertEqual(payload["overall_status"], "ok")

        suites = payload["suites"]
        self.assertEqual(len(suites), len(EXPECTED_SUITES))

        for suite, expected in zip(suites, EXPECTED_SUITES, strict=True):
            self.assertEqual(suite["name"], expected["name"])
            self.assertEqual(suite["status"], "ok")
            self.assertEqual(suite["case_count"], expected["case_count"])
            self.assertEqual(suite["top_k"], expected["top_k"])
            self.assertEqual(suite["top1"], expected["top1"])
            self.assertEqual(suite["top3"], expected["top3"])
            self.assertEqual(suite["topk"], expected["topk"])


if __name__ == "__main__":
    unittest.main()
