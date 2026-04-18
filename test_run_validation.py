from __future__ import annotations

import sys
import unittest

import run_validation


class RunValidationTests(unittest.TestCase):
    def test_collect_fast_test_targets_excludes_install_smoke(self) -> None:
        targets = run_validation.collect_fast_test_targets(run_validation.REPO_ROOT)

        self.assertIn("test_cli.py", targets)
        self.assertIn("test_run_validation.py", targets)
        self.assertNotIn("test_distribution_smoke.py", targets)

    def test_quick_profile_only_runs_fast_unit_suite(self) -> None:
        steps = run_validation.build_validation_steps("quick")

        self.assertEqual([step.name for step in steps], ["fast-unit"])
        self.assertEqual(steps[0].command[:3], (sys.executable, "-m", "unittest"))
        self.assertIn("test_cli.py", steps[0].command)
        self.assertNotIn("test_distribution_smoke.py", steps[0].command)

    def test_install_smoke_profile_is_explicit(self) -> None:
        steps = run_validation.build_validation_steps("install-smoke")

        self.assertEqual([step.name for step in steps], ["install-smoke"])
        self.assertEqual(
            steps[0].command,
            (sys.executable, "-m", "unittest", "test_distribution_smoke.py"),
        )

    def test_full_profile_keeps_install_smoke_and_runtime_regressions(self) -> None:
        steps = run_validation.build_validation_steps("full")

        self.assertEqual(
            [step.name for step in steps],
            ["fast-unit", "install-smoke", "round", "eval"],
        )
        self.assertEqual(
            steps[2].command,
            (
                sys.executable,
                "-m",
                "discrete_math_rag",
                "round",
                run_validation.DEFAULT_QUERY,
                "--json",
            ),
        )
        self.assertEqual(
            steps[3].command,
            (sys.executable, "-m", "discrete_math_rag", "eval", "--json"),
        )

    def test_ci_profile_matches_full_profile(self) -> None:
        self.assertEqual(
            run_validation.build_validation_steps("ci"),
            run_validation.build_validation_steps("full"),
        )


if __name__ == "__main__":
    unittest.main()
