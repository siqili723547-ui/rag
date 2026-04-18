from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from build_index_test_support import (
    build_expected_verification_payload,
    build_index_fixture_args,
    load_expected_index_payload,
)
from build_section_page_index import DEFAULT_VERIFY_TARGETS


BACKEND_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = BACKEND_DIR / "build_section_page_index.py"


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

    def test_rebuild_matches_fixture_payload(self) -> None:
        output_path = self.make_backend_temp_output()
        try:
            self.run_builder(
                "--output",
                str(output_path),
                *build_index_fixture_args(),
            )

            expected_payload = load_expected_index_payload()
            rebuilt_payload = json.loads(output_path.read_text(encoding="utf-8"))
            rebuilt_payload.pop("generated_at", None)

            self.assertEqual(rebuilt_payload, expected_payload)
        finally:
            output_path.unlink(missing_ok=True)

    def test_verify_prints_default_targets_from_fixture(self) -> None:
        output_path = self.make_backend_temp_output()
        try:
            completed = self.run_builder(
                "--output",
                str(output_path),
                *build_index_fixture_args(),
                "--verify",
            )
        finally:
            output_path.unlink(missing_ok=True)

        stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
        self.assertGreaterEqual(len(stdout_lines), 2)
        self.assertRegex(
            stdout_lines[0],
            r"^Generated 3 linked sections -> section_page_index\.test\..+\.json$",
        )

        verification_payload = json.loads("\n".join(stdout_lines[1:]))
        self.assertEqual(
            verification_payload,
            build_expected_verification_payload(DEFAULT_VERIFY_TARGETS),
        )


if __name__ == "__main__":
    unittest.main()
