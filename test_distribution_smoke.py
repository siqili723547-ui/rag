from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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

    def make_fixture_corpus(self, temp_path: Path) -> tuple[Path, Path]:
        corpus_root = temp_path / "fixture-corpus"
        note_root = corpus_root / "notes"
        page_index_path = corpus_root / "page-index.md"

        note_root.mkdir(parents=True)
        (note_root / "1.1.1 Sample.md").write_text(
            "# 1.1.1 Sample\nBody text for the install smoke fixture.\n",
            encoding="utf-8",
        )
        page_index_path.write_text(
            "| Section | Book | PDF |\n"
            "| --- | --- | --- |\n"
            "| 1.1.1 Sample | 1-1 | 10-10 |\n",
            encoding="utf-8",
        )
        return note_root, page_index_path

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
            note_root, page_index_path = self.make_fixture_corpus(temp_path)
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
                "--note-root",
                str(note_root),
                "--page-index",
                str(page_index_path),
                "--json",
                cwd=run_dir,
            )
            installed_assets_after = self.snapshot_installed_index_assets(venv_dir)

            build_payload = json.loads(build_completed.stdout)
            output_path = Path(str(build_payload["output_path"])).resolve()
            self.assertEqual(output_path, (run_dir / "section_page_index.json").resolve())
            self.assertTrue(output_path.exists())
            self.assertEqual(installed_assets_before, installed_assets_after)

    def test_editable_install_supports_cli_smoke(self) -> None:
        self.assert_install_mode_smoke("editable")

    def test_non_editable_install_supports_cli_smoke(self) -> None:
        self.assert_install_mode_smoke("install")

    def test_wheel_install_supports_cli_smoke(self) -> None:
        self.assert_install_mode_smoke("wheel")


if __name__ == "__main__":
    unittest.main()
