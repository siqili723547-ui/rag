from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
RUN_ROUND_PATH = BACKEND_DIR / "run_round.ps1"
EXPECTED_SUITE_NAMES = [
    "main_fixed",
    "definition_content_head",
    "single_char_definition_boundary",
    "multi_char_partial_overlap_boundary",
    "opening_definition_bridge_boundary",
    "concept_family_competition_boundary",
    "pure_partial_overlap_residual_boundary",
]


class RunRoundTests(unittest.TestCase):
    def run_round_json(self, *query: str) -> dict[str, object]:
        completed = subprocess.run(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(RUN_ROUND_PATH),
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

    def test_json_output_contains_default_probe_and_eval_contract(self) -> None:
        payload = self.run_round_json("什么是命题")

        self.assertEqual(payload["backend_dir"], str(BACKEND_DIR))
        self.assertEqual(payload["overall_status"], "ok")

        probe = payload["probe"]
        self.assertEqual(probe["exit_code"], 0)
        self.assertEqual(probe["payload"]["overall_status"], "ok")
        self.assertEqual(len(probe["payload"]["probes"]), 1)
        self.assertIsNone(probe["raw_stdout"])
        self.assertEqual(probe["stderr"], "")

        eval_payload = payload["eval"]
        self.assertEqual(eval_payload["exit_code"], 0)
        self.assertEqual(eval_payload["payload"]["overall_status"], "ok")
        self.assertIsNone(eval_payload["raw_stdout"])
        self.assertEqual(eval_payload["stderr"], "")

        suite_names = [suite["name"] for suite in eval_payload["payload"]["suites"]]
        self.assertEqual(suite_names, EXPECTED_SUITE_NAMES)


if __name__ == "__main__":
    unittest.main()
