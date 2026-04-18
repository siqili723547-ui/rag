from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from build_index_test_support import (
    PAGE_INDEX_PATH,
    SOURCE_ROOT,
    build_expected_verification_summary,
    build_index_fixture_args,
    load_expected_index_payload,
)


BACKEND_DIR = Path(__file__).resolve().parent
ANSWER_QUERY_PATH = BACKEND_DIR / "answer_query.py"
RETRIEVE_SECTIONS_PATH = BACKEND_DIR / "retrieve_sections.py"
BUILD_INDEX_PATH = BACKEND_DIR / "build_section_page_index.py"
RUN_EVAL_SUITE_PATH = BACKEND_DIR / "run_eval_suite.ps1"
RUN_ROUND_PATH = BACKEND_DIR / "run_round.ps1"
QUERY = "什么是命题"


class CliParityTests(unittest.TestCase):
    def run_python_command(
        self,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *args],
            cwd=BACKEND_DIR,
            check=check,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
            },
        )

    def run_python_json(self, *args: str) -> dict[str, object]:
        completed = self.run_python_command(*args)
        return json.loads(completed.stdout)

    def run_powershell_json(self, script_path: Path, *args: str) -> dict[str, object]:
        completed = subprocess.run(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                *args,
                "-Json",
            ],
            cwd=BACKEND_DIR,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return json.loads(completed.stdout)

    def run_cli_json(self, *args: str) -> dict[str, object]:
        return self.run_python_json("-m", "discrete_math_rag", *args, "--json")

    def make_backend_temp_output(self) -> Path:
        handle = tempfile.NamedTemporaryFile(
            dir=BACKEND_DIR,
            prefix="section_page_index.cli-test.",
            suffix=".json",
            delete=False,
        )
        handle.close()
        path = Path(handle.name)
        path.unlink(missing_ok=True)
        return path

    def test_answer_cli_matches_legacy_script_json(self) -> None:
        legacy_payload = self.run_python_json(
            str(ANSWER_QUERY_PATH),
            QUERY,
            "--json",
        )
        cli_payload = self.run_cli_json("answer", QUERY)

        self.assertEqual(cli_payload, legacy_payload)

    def test_retrieve_cli_matches_legacy_script_json(self) -> None:
        legacy_payload = self.run_python_json(
            str(RETRIEVE_SECTIONS_PATH),
            QUERY,
            "--json",
        )
        cli_payload = self.run_cli_json("retrieve", QUERY)

        self.assertEqual(cli_payload, legacy_payload)

    def test_eval_cli_matches_legacy_powershell_json(self) -> None:
        legacy_payload = self.run_powershell_json(RUN_EVAL_SUITE_PATH)
        cli_payload = self.run_cli_json("eval")

        self.assertEqual(cli_payload, legacy_payload)

    def test_round_cli_matches_legacy_powershell_json(self) -> None:
        legacy_payload = self.run_powershell_json(RUN_ROUND_PATH, QUERY)
        cli_payload = self.run_cli_json("round", QUERY)

        self.assertEqual(cli_payload, legacy_payload)

    def test_build_index_cli_matches_legacy_script_output(self) -> None:
        legacy_output_path = self.make_backend_temp_output()
        cli_output_path = self.make_backend_temp_output()

        try:
            self.run_python_command(
                str(BUILD_INDEX_PATH),
                "--output",
                str(legacy_output_path),
                *build_index_fixture_args(),
            )
            cli_summary = self.run_python_json(
                "-m",
                "discrete_math_rag",
                "build-index",
                "--output",
                str(cli_output_path),
                *build_index_fixture_args(),
                "--verify",
                "--json",
            )

            legacy_payload = json.loads(legacy_output_path.read_text(encoding="utf-8"))
            cli_payload = json.loads(cli_output_path.read_text(encoding="utf-8"))

            legacy_payload.pop("generated_at", None)
            cli_payload.pop("generated_at", None)

            expected_payload = load_expected_index_payload()
            self.assertEqual(cli_payload, legacy_payload)
            self.assertEqual(cli_payload, expected_payload)
            self.assertEqual(cli_summary["output_path"], str(cli_output_path))
            self.assertEqual(
                cli_summary["linked_sections_count"],
                expected_payload["linked_sections_count"],
            )
            self.assertEqual(
                cli_summary["note_sections_count"],
                expected_payload["note_sections_count"],
            )
            self.assertEqual(
                cli_summary["page_index_sections_count"],
                expected_payload["page_index_sections_count"],
            )
            self.assertEqual(
                cli_summary["unmapped_note_sections_count"],
                expected_payload["unmapped_note_sections_count"],
            )
            self.assertEqual(
                cli_summary["unmapped_page_index_sections_count"],
                expected_payload["unmapped_page_index_sections_count"],
            )
            self.assertEqual(
                cli_summary["verification"],
                build_expected_verification_summary(["3.2.1", "3.2.2", "10.2.1"]),
            )
        finally:
            legacy_output_path.unlink(missing_ok=True)
            cli_output_path.unlink(missing_ok=True)

    def test_root_help_lists_all_subcommands(self) -> None:
        completed = self.run_python_command("-m", "discrete_math_rag", "--help")

        self.assertEqual(completed.returncode, 0)
        self.assertIn("answer", completed.stdout)
        self.assertIn("retrieve", completed.stdout)
        self.assertIn("eval", completed.stdout)
        self.assertIn("round", completed.stdout)
        self.assertIn("build-index", completed.stdout)

    def test_each_subcommand_help_exits_zero(self) -> None:
        for subcommand in ("answer", "retrieve", "eval", "round", "build-index"):
            with self.subTest(subcommand=subcommand):
                completed = self.run_python_command(
                    "-m",
                    "discrete_math_rag",
                    subcommand,
                    "--help",
                )
                self.assertEqual(completed.returncode, 0)
                self.assertIn("usage: discrete-math-rag", completed.stdout)

    def test_version_matches_package_version(self) -> None:
        completed = self.run_python_command("-m", "discrete_math_rag", "--version")

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.strip(), "discrete-math-rag 0.1.0")

    def test_bad_path_errors_are_plain_cli_messages(self) -> None:
        cases = [
            (
                ("answer", QUERY, "--index", "missing-index.json"),
                "index file not found:",
            ),
            (
                ("retrieve", "--verify", "--verify-cases", "missing-cases.json"),
                "verification cases file not found:",
            ),
            (
                ("eval", "--index", "missing-index.json"),
                "index file not found:",
            ),
        ]

        for argv, expected_error in cases:
            with self.subTest(argv=argv):
                completed = self.run_python_command(
                    "-m",
                    "discrete_math_rag",
                    *argv,
                    check=False,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(completed.stdout, "")
                self.assertIn(expected_error, completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)

    def test_invalid_numeric_args_are_plain_cli_messages(self) -> None:
        cases = [
            (
                ("retrieve", QUERY, "--snippet-chars", "0"),
                "--snippet-chars must be a positive integer",
            ),
            (
                ("round", QUERY, "--top-k", "0", "--skip-eval"),
                "--top-k must be a positive integer",
            ),
            (
                ("round", QUERY, "--snippet-chars", "0", "--skip-eval"),
                "--snippet-chars must be a positive integer",
            ),
        ]

        for argv, expected_error in cases:
            with self.subTest(argv=argv):
                completed = self.run_python_command(
                    "-m",
                    "discrete_math_rag",
                    *argv,
                    check=False,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(completed.stdout, "")
                self.assertIn(expected_error, completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)

    def test_build_index_bad_path_errors_are_plain_cli_messages(self) -> None:
        cases = [
            (
                (
                    "build-index",
                    "--note-root",
                    "missing-note-root",
                    "--page-index",
                    str(PAGE_INDEX_PATH),
                ),
                "note root not found:",
            ),
            (
                (
                    "build-index",
                    "--note-root",
                    str(SOURCE_ROOT),
                    "--page-index",
                    "missing-page-index",
                ),
                "page index not found:",
            ),
        ]

        for argv, expected_error in cases:
            with self.subTest(argv=argv):
                completed = self.run_python_command(
                    "-m",
                    "discrete_math_rag",
                    *argv,
                    check=False,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(completed.stdout, "")
                self.assertIn(expected_error, completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)

    def test_build_index_verify_missing_target_fails_before_writing_output(self) -> None:
        for extra_args in ((), ("--json",)):
            with self.subTest(extra_args=extra_args):
                output_path = self.make_backend_temp_output()
                try:
                    completed = self.run_python_command(
                        "-m",
                        "discrete_math_rag",
                        "build-index",
                        "--output",
                        str(output_path),
                        *build_index_fixture_args(),
                        "--verify",
                        "--section",
                        "999.9.9",
                        *extra_args,
                        check=False,
                    )
                finally:
                    output_path.unlink(missing_ok=True)

                self.assertEqual(completed.returncode, 1)
                self.assertEqual(completed.stdout, "")
                self.assertIn("missing target sections: 999.9.9", completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)
                self.assertFalse(output_path.exists())

    def test_build_index_json_verification_preserves_requested_section_order(self) -> None:
        requested_sections = ["3.2.2", "10.2.1"]

        output_path = self.make_backend_temp_output()
        try:
            summary = self.run_python_json(
                "-m",
                "discrete_math_rag",
                "build-index",
                "--output",
                str(output_path),
                *build_index_fixture_args(),
                "--verify",
                "--section",
                requested_sections[0],
                "--section",
                requested_sections[1],
                "--json",
            )
        finally:
            output_path.unlink(missing_ok=True)

        self.assertEqual(
            [record["section_id"] for record in summary["verification"]],
            requested_sections,
        )


if __name__ == "__main__":
    unittest.main()
