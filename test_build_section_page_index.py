from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from build_section_page_index import DEFAULT_VERIFY_TARGETS


BACKEND_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = BACKEND_DIR / "build_section_page_index.py"
CURRENT_INDEX_PATH = BACKEND_DIR / "section_page_index.json"


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


class BuildSectionPageIndexTests(unittest.TestCase):
    def run_builder(self, *extra_args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *extra_args],
            cwd=BACKEND_DIR,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def make_backend_temp_output(self) -> Path:
        handle = tempfile.NamedTemporaryFile(
            dir=BACKEND_DIR,
            prefix="section_page_index.test.",
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

    def test_rebuild_matches_checked_in_index(self) -> None:
        self.require_external_corpus()
        output_path = self.make_backend_temp_output()
        try:
            self.run_builder(
                "--output",
                str(output_path),
                "--note-root",
                str(NOTE_ROOT),
                "--page-index",
                str(PAGE_INDEX_PATH),
                "--source-root",
                str(SOURCE_ROOT),
            )

            current_payload = json.loads(CURRENT_INDEX_PATH.read_text(encoding="utf-8"))
            rebuilt_payload = json.loads(output_path.read_text(encoding="utf-8"))

            current_payload.pop("generated_at", None)
            rebuilt_payload.pop("generated_at", None)

            self.assertEqual(rebuilt_payload, current_payload)
        finally:
            output_path.unlink(missing_ok=True)

    def test_verify_prints_default_targets(self) -> None:
        self.require_external_corpus()
        output_path = self.make_backend_temp_output()
        try:
            completed = self.run_builder(
                "--output",
                str(output_path),
                "--note-root",
                str(NOTE_ROOT),
                "--page-index",
                str(PAGE_INDEX_PATH),
                "--source-root",
                str(SOURCE_ROOT),
                "--verify",
            )
        finally:
            output_path.unlink(missing_ok=True)

        stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
        self.assertGreaterEqual(len(stdout_lines), 2)
        self.assertIn("Generated 143 linked sections ->", stdout_lines[0])

        verification_payload = json.loads("\n".join(stdout_lines[1:]))
        self.assertEqual(
            [item["section_id"] for item in verification_payload],
            DEFAULT_VERIFY_TARGETS,
        )
        self.assertEqual(verification_payload[0]["title"], "命题")
        self.assertEqual(verification_payload[0]["pdf_page_start"], 67)
        self.assertEqual(verification_payload[1]["title"], "命题联结词")
        self.assertEqual(verification_payload[2]["title"], "树的定义与性质")


if __name__ == "__main__":
    unittest.main()
