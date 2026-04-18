from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
ANSWER_QUERY_PATH = BACKEND_DIR / "answer_query.py"
RETRIEVE_SECTIONS_PATH = BACKEND_DIR / "retrieve_sections.py"
BUILD_INDEX_PATH = BACKEND_DIR / "build_section_page_index.py"
RUN_EVAL_SUITE_PATH = BACKEND_DIR / "run_eval_suite.ps1"
RUN_ROUND_PATH = BACKEND_DIR / "run_round.ps1"
QUERY = "什么是命题"


def resolve_source_root() -> Path | None:
    env_path = os.environ.get("DISCRETE_MATH_RAG_SOURCE_ROOT")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            BACKEND_DIR.parent / "Obsidian Vault",
            Path.home() / "Documents" / "Obsidian Vault",
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


SOURCE_ROOT = resolve_source_root()
BOOK_ROOT = SOURCE_ROOT / "math" / "离散数学及其应用" if SOURCE_ROOT else None
NOTE_ROOT = BOOK_ROOT / "笔记" if BOOK_ROOT else None
PAGE_INDEX_PATH = BOOK_ROOT / "页码索引.md" if BOOK_ROOT else None


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

    def require_external_corpus(self) -> None:
        if SOURCE_ROOT is None or NOTE_ROOT is None or PAGE_INDEX_PATH is None:
            self.skipTest("External corpus root not found.")
        if not NOTE_ROOT.exists():
            self.skipTest(f"External note root not found: {NOTE_ROOT}")
        if not PAGE_INDEX_PATH.exists():
            self.skipTest(f"External page index not found: {PAGE_INDEX_PATH}")

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
        self.require_external_corpus()
        legacy_output_path = self.make_backend_temp_output()
        cli_output_path = self.make_backend_temp_output()

        try:
            self.run_python_command(
                str(BUILD_INDEX_PATH),
                "--output",
                str(legacy_output_path),
                "--note-root",
                str(NOTE_ROOT),
                "--page-index",
                str(PAGE_INDEX_PATH),
                "--source-root",
                str(SOURCE_ROOT),
            )
            self.run_python_json(
                "-m",
                "discrete_math_rag",
                "build-index",
                "--output",
                str(cli_output_path),
                "--note-root",
                str(NOTE_ROOT),
                "--page-index",
                str(PAGE_INDEX_PATH),
                "--source-root",
                str(SOURCE_ROOT),
                "--json",
            )

            legacy_payload = json.loads(legacy_output_path.read_text(encoding="utf-8"))
            cli_payload = json.loads(cli_output_path.read_text(encoding="utf-8"))

            legacy_payload.pop("generated_at", None)
            cli_payload.pop("generated_at", None)

            self.assertEqual(cli_payload, legacy_payload)
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


if __name__ == "__main__":
    unittest.main()
