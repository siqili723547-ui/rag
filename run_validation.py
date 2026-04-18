from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_QUERY = "什么是命题"
SLOW_TEST_TARGETS = ("test_distribution_smoke.py",)


@dataclass(frozen=True)
class ValidationStep:
    name: str
    command: tuple[str, ...]


def collect_fast_test_targets(repo_root: Path) -> list[str]:
    return sorted(
        path.name
        for path in repo_root.glob("test_*.py")
        if path.name not in SLOW_TEST_TARGETS
    )


def build_validation_steps(
    profile: str,
    query: str = DEFAULT_QUERY,
) -> list[ValidationStep]:
    fast_targets = collect_fast_test_targets(REPO_ROOT)
    if not fast_targets:
        raise SystemExit("No fast unit test targets found.")

    profiles = {
        "quick": [
            ValidationStep(
                "fast-unit",
                (sys.executable, "-m", "unittest", *fast_targets),
            )
        ],
        "install-smoke": [
            ValidationStep(
                "install-smoke",
                (sys.executable, "-m", "unittest", *SLOW_TEST_TARGETS),
            )
        ],
        "round": [
            ValidationStep(
                "round",
                (
                    sys.executable,
                    "-m",
                    "discrete_math_rag",
                    "round",
                    query,
                    "--json",
                ),
            )
        ],
        "eval": [
            ValidationStep(
                "eval",
                (sys.executable, "-m", "discrete_math_rag", "eval", "--json"),
            )
        ],
    }
    profiles["full"] = [
        *profiles["quick"],
        *profiles["install-smoke"],
        *profiles["round"],
        *profiles["eval"],
    ]
    profiles["ci"] = list(profiles["full"])

    try:
        return profiles[profile]
    except KeyError as exc:
        available = ", ".join(sorted(profiles))
        raise SystemExit(f"Unknown validation profile: {profile}. Available: {available}") from exc


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run layered validation profiles for discrete-math-rag.",
    )
    parser.add_argument(
        "profile",
        nargs="?",
        default="quick",
        choices=("quick", "install-smoke", "round", "eval", "full", "ci"),
        help="Validation profile to run. Defaults to quick.",
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help="Probe query used by the round/full/ci profiles.",
    )
    return parser.parse_args(argv)


def run_validation_step(step: ValidationStep) -> None:
    print(f"==> {step.name}: {' '.join(step.command)}")
    subprocess.run(step.command, cwd=REPO_ROOT, check=True)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    for step in build_validation_steps(args.profile, query=args.query):
        run_validation_step(step)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
