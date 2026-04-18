from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from build_index_test_support import build_index_fixture_args, load_expected_index_payload


BACKEND_DIR = Path(__file__).resolve().parent
QUERY = "什么是命题"


class DistributionSmokeTests(unittest.TestCase):
    def run_command(
        self,
        *args: str,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(args),
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
            },
        )

    def find_console_script(self, venv_dir: Path) -> Path:
        scripts_dir = venv_dir / "Scripts"
        for candidate in (
            "discrete-math-rag.exe",
            "discrete-math-rag.cmd",
            "discrete-math-rag",
        ):
            path = scripts_dir / candidate
            if path.exists():
                return path
        raise AssertionError("Installed console script not found in venv Scripts directory.")

    def digest_file(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def snapshot_installed_index_assets(self, venv_dir: Path) -> dict[str, str]:
        return {
            path.relative_to(venv_dir).as_posix(): self.digest_file(path)
            for path in sorted(venv_dir.rglob("section_page_index*.json"))
        }

    def install_into_venv(
        self,
        install_mode: str,
        temp_path: Path,
    ) -> tuple[Path, Path]:
        venv_dir = temp_path / "venv"
        self.run_command(sys.executable, "-m", "venv", str(venv_dir), cwd=BACKEND_DIR)

        venv_python = venv_dir / "Scripts" / "python.exe"
        if install_mode == "editable":
            self.run_command(
                str(venv_python),
                "-m",
                "pip",
                "install",
                "-e",
                ".",
                cwd=BACKEND_DIR,
            )
            return venv_dir, venv_python

        if install_mode == "install":
            self.run_command(
                str(venv_python),
                "-m",
                "pip",
                "install",
                ".",
                cwd=BACKEND_DIR,
            )
            return venv_dir, venv_python

        if install_mode == "wheel":
            dist_dir = temp_path / "dist"
            dist_dir.mkdir()
            self.run_command(
                sys.executable,
                "-m",
                "pip",
                "wheel",
                ".",
                "--no-deps",
                "-w",
                str(dist_dir),
                cwd=BACKEND_DIR,
            )
            wheel_path = next(dist_dir.glob("*.whl"))
            self.run_command(
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                str(wheel_path),
                cwd=BACKEND_DIR,
            )
            return venv_dir, venv_python

        raise AssertionError(f"Unsupported install mode: {install_mode}")

    def assert_install_mode_smoke(self, install_mode: str) -> None:
        with tempfile.TemporaryDirectory(
            prefix="discrete-math-rag.dist-smoke.",
        ) as temp_dir:
            temp_path = Path(temp_dir)
            run_dir = temp_path / "run"
            run_dir.mkdir()
            venv_dir, venv_python = self.install_into_venv(install_mode, temp_path)
            console_script = self.find_console_script(venv_dir)

            answer_completed = self.run_command(
                str(venv_python),
                "-m",
                "discrete_math_rag",
                "answer",
                QUERY,
                "--json",
                cwd=run_dir,
            )
            answer_payload = json.loads(answer_completed.stdout)
            self.assertEqual(answer_payload["query"], QUERY)
            self.assertIn("answer", answer_payload)
            self.assertIn("supporting_matches", answer_payload)

            eval_completed = self.run_command(
                str(console_script),
                "eval",
                "--json",
                cwd=run_dir,
            )
            eval_payload = json.loads(eval_completed.stdout)
            self.assertEqual(eval_payload["overall_status"], "ok")

            installed_assets_before = self.snapshot_installed_index_assets(venv_dir)
            build_completed = self.run_command(
                str(venv_python),
                "-m",
                "discrete_math_rag",
                "build-index",
                *build_index_fixture_args(),
                "--verify",
                "--json",
                cwd=run_dir,
            )
            installed_assets_after = self.snapshot_installed_index_assets(venv_dir)

            expected_payload = load_expected_index_payload()
            build_payload = json.loads(build_completed.stdout)
            output_path = Path(str(build_payload["output_path"])).resolve()
            self.assertEqual(output_path, (run_dir / "section_page_index.json").resolve())
            self.assertTrue(output_path.exists())
            output_payload = json.loads(output_path.read_text(encoding="utf-8"))
            output_payload.pop("generated_at", None)
            self.assertEqual(output_payload, expected_payload)
            self.assertEqual(
                build_payload["linked_sections_count"],
                expected_payload["linked_sections_count"],
            )
            self.assertEqual(
                build_payload["note_sections_count"],
                expected_payload["note_sections_count"],
            )
            self.assertEqual(
                build_payload["page_index_sections_count"],
                expected_payload["page_index_sections_count"],
            )
            self.assertEqual(
                build_payload["unmapped_note_sections_count"],
                expected_payload["unmapped_note_sections_count"],
            )
            self.assertEqual(
                build_payload["unmapped_page_index_sections_count"],
                expected_payload["unmapped_page_index_sections_count"],
            )
            self.assertEqual(build_payload["verification"], expected_payload["sections"])
            self.assertEqual(installed_assets_before, installed_assets_after)

    def test_editable_install_supports_cli_smoke(self) -> None:
        self.assert_install_mode_smoke("editable")

    def test_non_editable_install_supports_cli_smoke(self) -> None:
        self.assert_install_mode_smoke("install")

    def test_wheel_install_supports_cli_smoke(self) -> None:
        self.assert_install_mode_smoke("wheel")


if __name__ == "__main__":
    unittest.main()
