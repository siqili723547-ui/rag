from __future__ import annotations

import argparse
import json
import sys
import sysconfig
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import answer_query
import build_section_page_index
import retrieve_sections
from _build_section_page_index_impl import (
    DEFAULT_VERIFY_TARGETS,
    build_records,
    configure_stdio,
    load_note_sections,
    parse_page_index,
    print_verification,
    write_output,
)

from discrete_math_rag import __version__


BACKEND_DIR = Path(__file__).resolve().parent.parent
INSTALL_DATA_DIR = Path(sysconfig.get_path("data")).resolve()


def resolve_runtime_asset(filename: str) -> Path:
    for candidate in (
        BACKEND_DIR / filename,
        INSTALL_DATA_DIR / filename,
    ):
        if candidate.exists():
            return candidate
    return BACKEND_DIR / filename


DEFAULT_INDEX_PATH = resolve_runtime_asset("section_page_index.json")
DEFAULT_VERIFY_CASES_PATH = resolve_runtime_asset("section_retrieval_eval_cases.json")
DEFAULT_BUILD_INDEX_OUTPUT = Path("section_page_index.json")
EVAL_SUITES = (
    {"name": "main_fixed", "file": "section_retrieval_eval_cases.json", "top_k": 3},
    {
        "name": "definition_content_head",
        "file": "section_retrieval_eval_cases_definition_content_head.json",
        "top_k": 3,
    },
    {
        "name": "single_char_definition_boundary",
        "file": "section_retrieval_eval_cases_single_char_definition_boundary.json",
        "top_k": 5,
    },
    {
        "name": "multi_char_partial_overlap_boundary",
        "file": "section_retrieval_eval_cases_multi_char_partial_overlap_boundary.json",
        "top_k": 3,
    },
    {
        "name": "opening_definition_bridge_boundary",
        "file": "section_retrieval_eval_cases_opening_definition_bridge_boundary.json",
        "top_k": 3,
    },
    {
        "name": "concept_family_competition_boundary",
        "file": "section_retrieval_eval_cases_concept_family_competition_boundary.json",
        "top_k": 5,
    },
    {
        "name": "pure_partial_overlap_residual_boundary",
        "file": "section_retrieval_eval_cases_pure_partial_overlap_residual_boundary.json",
        "top_k": 5,
    },
)


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    payload: dict[str, object] | None
    stdout: str
    stderr: str = ""
    parse_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.payload is not None


def dumps_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def dumps_json_stdout(payload: object) -> str:
    return dumps_json(payload).replace("\n", "\r\n")


def indent_block(text: str, prefix: str = "    ") -> str:
    return prefix + text.replace("\n", f"\n{prefix}")


def resolve_existing_file(path: Path, label: str) -> Path:
    resolved_path = path.resolve()
    if not resolved_path.exists():
        raise SystemExit(f"{label} not found: {resolved_path}")
    if not resolved_path.is_file():
        raise SystemExit(f"{label} must be a file: {resolved_path}")
    return resolved_path


def resolve_existing_directory(path: Path, label: str) -> Path:
    resolved_path = path.resolve()
    if not resolved_path.exists():
        raise SystemExit(f"{label} not found: {resolved_path}")
    if not resolved_path.is_dir():
        raise SystemExit(f"{label} must be a directory: {resolved_path}")
    return resolved_path


def resolve_build_output_path(path: Path) -> Path:
    if path.is_absolute():
        return path.resolve()
    return (Path.cwd() / path).resolve()


def build_retrieve_payload(
    query: str,
    index_path: Path,
    top_k: int,
    snippet_chars: int,
) -> dict[str, object]:
    sections = retrieve_sections.load_sections(index_path.resolve())
    results = retrieve_sections.rank_sections(sections, query, top_k)
    return {
        "query": query,
        "top_k": top_k,
        "results": [
            result.to_payload(query, snippet_chars) for result in results
        ],
    }


def run_retrieve_query(
    query: str,
    index_path: Path,
    top_k: int,
    snippet_chars: int,
) -> CommandResult:
    try:
        payload = build_retrieve_payload(query, index_path, top_k, snippet_chars)
    except SystemExit as exc:
        return CommandResult(
            exit_code=int(exc.code) if isinstance(exc.code, int) else 1,
            payload=None,
            stdout="",
            stderr=str(exc),
        )

    return CommandResult(
        exit_code=0,
        payload=payload,
        stdout=dumps_json_stdout(payload),
    )


def run_probe_queries(
    queries: Sequence[str],
    index_path: Path,
    top_k: int,
    snippet_chars: int,
) -> dict[str, object]:
    parsed_results: list[dict[str, object]] = []
    has_failure = False

    for query in queries:
        result = run_retrieve_query(query, index_path, top_k, snippet_chars)
        if not result.ok:
            has_failure = True

        payload = result.payload or {"top_k": top_k, "results": []}
        parsed_results.append(
            {
                "query": query,
                "exit_code": result.exit_code,
                "status": "ok" if result.ok else "failed",
                "top_k": payload["top_k"],
                "results": payload["results"],
                "stdout": result.stdout,
                "stderr": result.stderr,
                "parse_error": result.parse_error,
            }
        )

    return {
        "backend_dir": str(BACKEND_DIR),
        "overall_status": "failed" if has_failure else "ok",
        "probes": parsed_results,
    }


def summarize_eval_suite(summary: dict[str, object]) -> dict[str, object]:
    case_count = int(summary["case_count"])
    return {
        "case_count": case_count,
        "top_k": int(summary["top_k"]),
        "top1": f"{summary['top1_hits']}/{case_count}",
        "top3": f"{summary['top3_hits']}/{case_count}",
        "topk": f"{summary['top_k_hits']}/{case_count}",
    }


def run_eval_suite(index_path: Path) -> dict[str, object]:
    sections = retrieve_sections.load_sections(index_path.resolve())
    suite_results: list[dict[str, object]] = []
    has_failure = False

    for dataset in EVAL_SUITES:
        cases_path = resolve_runtime_asset(str(dataset["file"]))
        try:
            verification_cases = retrieve_sections.load_verification_cases(
                cases_path.resolve()
            )
            verification_results = retrieve_sections.evaluate_verification_cases(
                sections=sections,
                cases=verification_cases,
                top_k=dataset["top_k"],
            )
            payload = retrieve_sections.build_verification_payload(
                verification_results=verification_results,
                top_k=dataset["top_k"],
                snippet_chars=120,
            )
            failures = retrieve_sections.collect_verification_failures(
                verification_results
            )
            if failures:
                exit_code = 1
                stderr = "verification failed:\n" + "\n".join(
                    f"- {failure}" for failure in failures
                )
                has_failure = True
            else:
                exit_code = 0
                stderr = ""
        except SystemExit as exc:
            payload = None
            exit_code = int(exc.code) if isinstance(exc.code, int) else 1
            stderr = str(exc)
            has_failure = True

        summary = payload["summary"] if payload is not None else None
        suite_summary = summarize_eval_suite(summary) if summary is not None else None
        stdout = dumps_json_stdout(payload) if payload is not None else ""

        suite_results.append(
            {
                "name": dataset["name"],
                "exit_code": exit_code,
                "status": (
                    "ok" if exit_code == 0 and suite_summary is not None else "failed"
                ),
                "case_count": (
                    suite_summary["case_count"] if suite_summary is not None else None
                ),
                "top_k": suite_summary["top_k"] if suite_summary is not None else None,
                "top1": suite_summary["top1"] if suite_summary is not None else None,
                "top3": suite_summary["top3"] if suite_summary is not None else None,
                "topk": suite_summary["topk"] if suite_summary is not None else None,
                "stdout": stdout,
                "stderr": stderr,
                "parse_error": None,
            }
        )

    return {
        "backend_dir": str(BACKEND_DIR),
        "overall_status": "failed" if has_failure else "ok",
        "suites": suite_results,
    }


def build_round_payload(
    queries: Sequence[str],
    index_path: Path,
    top_k: int,
    snippet_chars: int,
    skip_probe: bool,
    skip_eval: bool,
) -> dict[str, object]:
    if skip_probe and skip_eval:
        raise SystemExit("At least one of --skip-probe / --skip-eval must be false.")

    probe_payload = None
    if not skip_probe:
        probe_payload = run_probe_queries(
            queries=queries,
            index_path=index_path,
            top_k=top_k,
            snippet_chars=snippet_chars,
        )

    eval_payload = None
    if not skip_eval:
        eval_payload = run_eval_suite(index_path=index_path)

    overall_failure = (
        (probe_payload is not None and probe_payload["overall_status"] != "ok")
        or (eval_payload is not None and eval_payload["overall_status"] != "ok")
    )

    return {
        "backend_dir": str(BACKEND_DIR),
        "overall_status": "failed" if overall_failure else "ok",
        "probe": (
            {
                "exit_code": 0 if probe_payload["overall_status"] == "ok" else 1,
                "payload": probe_payload,
                "stderr": "",
                "raw_stdout": None,
            }
            if probe_payload is not None
            else None
        ),
        "eval": (
            {
                "exit_code": 0 if eval_payload["overall_status"] == "ok" else 1,
                "payload": eval_payload,
                "stderr": "",
                "raw_stdout": None,
            }
            if eval_payload is not None
            else None
        ),
    }


def display_path(path: Path, base: Path) -> str:
    return build_section_page_index.display_path(path, base)


def default_source_root(note_root: Path, page_index_path: Path) -> Path:
    return build_section_page_index.default_source_root(note_root, page_index_path)


def build_index_payload(
    note_root: Path,
    page_index_path: Path,
    source_root: Path | None,
    include_unmapped_second_level_notes: bool,
) -> dict[str, object]:
    resolved_source_root = source_root or default_source_root(note_root, page_index_path)

    note_sections = load_note_sections(note_root, resolved_source_root)
    page_index_entries = parse_page_index(page_index_path)
    records = build_records(
        note_sections,
        page_index_entries,
        include_unmapped_second_level_notes=include_unmapped_second_level_notes,
    )
    linked_section_ids = {record["section_id"] for record in records}

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note_root": display_path(note_root, resolved_source_root),
        "page_index_path": display_path(page_index_path, resolved_source_root),
        "linked_sections_count": len(records),
        "note_sections_count": len(note_sections),
        "page_index_sections_count": len(page_index_entries),
        "unmapped_note_sections_count": len(set(note_sections) - linked_section_ids),
        "unmapped_page_index_sections_count": len(
            set(page_index_entries) - linked_section_ids
        ),
        "sections": records,
    }
    return payload


def collect_build_index_verification_payload(
    records: Sequence[dict[str, object]],
    target_ids: Sequence[str],
) -> list[dict[str, object]]:
    record_by_id = {str(record["section_id"]): record for record in records}
    missing = [target_id for target_id in target_ids if target_id not in record_by_id]
    if missing:
        raise SystemExit(f"missing target sections: {', '.join(missing)}")
    return [record_by_id[target_id] for target_id in target_ids]


def collect_queries(
    query_args: Sequence[str] | None,
    query_file: Path | None,
) -> list[str]:
    if query_file is not None:
        query_file = resolve_existing_file(query_file, "query file")
        return [
            line.strip()
            for line in query_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    queries = [query.strip() for query in query_args or [] if query.strip()]
    if not queries:
        raise SystemExit("Probe step requires at least one query or --query-file.")
    return queries


def print_eval_suite(payload: dict[str, object]) -> None:
    print("Parallel evaluation suite")
    print(f"Backend: {payload['backend_dir']}")
    print("")

    for suite in payload["suites"]:
        if suite["status"] == "ok":
            summary_parts = [
                f"Top1 {suite['top1']}",
                f"Top3 {suite['top3']}",
            ]
            if suite["top_k"] != 3:
                summary_parts.append(f"Top{suite['top_k']} {suite['topk']}")
            print(f"[OK] {suite['name']}: {' | '.join(summary_parts)}")
            continue

        print(f"[FAIL] {suite['name']}: exit_code={suite['exit_code']}")
        if suite["parse_error"]:
            print(f"  parse_error: {suite['parse_error']}")
        if suite["stderr"]:
            print("  stderr:")
            print(indent_block(suite["stderr"]))
        if suite["stdout"]:
            print("  stdout:")
            print(indent_block(suite["stdout"]))


def print_probe_payload(payload: dict[str, object]) -> None:
    print("Parallel query probe")
    print(f"Backend: {payload['backend_dir']}")
    print("")

    for probe in payload["probes"]:
        print(f"query: {probe['query']}")
        if probe["status"] != "ok":
            print(f"  status: failed (exit_code={probe['exit_code']})")
            if probe["parse_error"]:
                print(f"  parse_error: {probe['parse_error']}")
            if probe["stderr"]:
                print("  stderr:")
                print(indent_block(probe["stderr"]))
            if probe["stdout"]:
                print("  stdout:")
                print(indent_block(probe["stdout"]))
            print("")
            continue

        if not probe["results"]:
            print("  no matches")
            print("")
            continue

        for index, result in enumerate(probe["results"], start=1):
            print(
                f"  {index}. [{result['section_id']}] {result['title']} "
                f"(score={result['score']})"
            )
            print(f"     source: {result['source_path']}")
            print(f"     pdf: {result['pdf_page_start']}-{result['pdf_page_end']}")
            reasons = ", ".join(result["match_reasons"]) or "token overlap"
            print(f"     reasons: {reasons}")
            print(f"     snippet: {result['snippet']}")
        print("")


def print_round_payload(payload: dict[str, object]) -> None:
    print("RAG round runner")
    print(f"Backend: {payload['backend_dir']}")
    print("")

    if payload["probe"] is not None:
        print("=== Probe ===")
        print_probe_payload(payload["probe"]["payload"])
        print("")

    if payload["eval"] is not None:
        print("=== Eval ===")
        print_eval_suite(payload["eval"]["payload"])
        print("")


def add_shared_index_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX_PATH,
        help="Path to section_page_index.json.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="discrete-math-rag",
        description="Unified CLI for the discrete-math-rag backend.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    answer_parser = subparsers.add_parser(
        "answer",
        help="Generate a concise answer from the top retrieved section.",
    )
    answer_parser.add_argument("query", help="Natural-language question to answer.")
    add_shared_index_argument(answer_parser)
    answer_parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="How many retrieved sections to consider.",
    )
    answer_parser.add_argument(
        "--answer-chars",
        type=int,
        default=220,
        help="Maximum answer length in characters.",
    )
    answer_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the answer payload as JSON.",
    )

    retrieve_parser = subparsers.add_parser(
        "retrieve",
        help="Retrieve relevant sections or run fixed retrieval verification.",
    )
    retrieve_parser.add_argument(
        "query",
        nargs="?",
        help="Natural-language query to retrieve relevant sections for.",
    )
    add_shared_index_argument(retrieve_parser)
    retrieve_parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="How many top-ranked sections to return.",
    )
    retrieve_parser.add_argument(
        "--snippet-chars",
        type=int,
        default=120,
        help="Maximum snippet length in characters.",
    )
    retrieve_parser.add_argument(
        "--verify",
        action="store_true",
        help="Run the fixed retrieval verification cases.",
    )
    retrieve_parser.add_argument(
        "--verify-cases",
        type=Path,
        default=DEFAULT_VERIFY_CASES_PATH,
        help="Path to the fixed retrieval verification cases JSON file.",
    )
    retrieve_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the retrieval or verification payload as JSON.",
    )

    eval_parser = subparsers.add_parser(
        "eval",
        help="Run the fixed retrieval evaluation suites.",
    )
    add_shared_index_argument(eval_parser)
    eval_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the evaluation payload as JSON.",
    )

    round_parser = subparsers.add_parser(
        "round",
        help="Run the default probe-then-eval round.",
    )
    round_parser.add_argument(
        "query",
        nargs="*",
        help="Probe query or queries to run before evaluation.",
    )
    round_parser.add_argument(
        "--query-file",
        type=Path,
        help="Read probe queries from a UTF-8 text file.",
    )
    add_shared_index_argument(round_parser)
    round_parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="How many top-ranked sections to return during probe.",
    )
    round_parser.add_argument(
        "--snippet-chars",
        type=int,
        default=120,
        help="Maximum snippet length in characters for probe output.",
    )
    round_parser.add_argument(
        "--skip-probe",
        action="store_true",
        help="Skip the probe step.",
    )
    round_parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip the fixed evaluation step.",
    )
    round_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the round payload as JSON.",
    )

    build_index_parser = subparsers.add_parser(
        "build-index",
        help="Build section_page_index.json from the external note corpus.",
    )
    build_index_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_BUILD_INDEX_OUTPUT,
        help=(
            "Where to write the generated JSON index. Defaults to "
            "./section_page_index.json in the current working directory."
        ),
    )
    build_index_parser.add_argument(
        "--note-root",
        type=Path,
        required=True,
        help="Path to the external note corpus root.",
    )
    build_index_parser.add_argument(
        "--page-index",
        type=Path,
        required=True,
        help="Path to the external page-index markdown file.",
    )
    build_index_parser.add_argument(
        "--source-root",
        type=Path,
        help="Optional shared root used to relativize source paths.",
    )
    build_index_parser.add_argument(
        "--verify",
        action="store_true",
        help="Print selected section mappings after building the JSON index.",
    )
    build_index_parser.add_argument(
        "--section",
        action="append",
        dest="sections",
        default=[],
        help="Section id to verify. Can be passed multiple times.",
    )
    build_index_parser.add_argument(
        "--include-unmapped-second-level-notes",
        action="store_true",
        help="Include unmatched second-level notes that self-report inline PDF pages.",
    )
    build_index_parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable build summary.",
    )

    return parser


def handle_answer(args: argparse.Namespace) -> int:
    if args.top_k <= 0:
        raise SystemExit("--top-k must be a positive integer")
    if args.answer_chars <= 0:
        raise SystemExit("--answer-chars must be a positive integer")

    index_path = resolve_existing_file(args.index, "index file")
    sections = retrieve_sections.load_sections(index_path)
    payload = answer_query.build_answer_payload(
        sections=sections,
        query=args.query,
        top_k=args.top_k,
        answer_chars=args.answer_chars,
    )

    if args.json:
        print(dumps_json(payload))
        return 0

    answer_query.print_answer(payload)
    return 0


def handle_retrieve(args: argparse.Namespace) -> int:
    if args.top_k <= 0:
        raise SystemExit("--top-k must be a positive integer")
    if args.snippet_chars <= 0:
        raise SystemExit("--snippet-chars must be a positive integer")

    index_path = resolve_existing_file(args.index, "index file")
    sections = retrieve_sections.load_sections(index_path)

    if args.verify:
        verify_cases_path = resolve_existing_file(
            args.verify_cases,
            "verification cases file",
        )
        verification_cases = retrieve_sections.load_verification_cases(
            verify_cases_path
        )
        verification_results = retrieve_sections.evaluate_verification_cases(
            sections=sections,
            cases=verification_cases,
            top_k=args.top_k,
        )
        payload = retrieve_sections.build_verification_payload(
            verification_results=verification_results,
            top_k=args.top_k,
            snippet_chars=args.snippet_chars,
        )

        if args.json:
            print(dumps_json(payload))
        else:
            retrieve_sections.print_verification_report(
                verification_results=verification_results,
                top_k=args.top_k,
                snippet_chars=args.snippet_chars,
            )

        failures = retrieve_sections.collect_verification_failures(verification_results)
        if failures:
            raise SystemExit(
                "verification failed:\n"
                + "\n".join(f"- {failure}" for failure in failures)
            )
        return 0

    if not args.query:
        raise SystemExit("query is required unless --verify is used")

    payload = build_retrieve_payload(
        query=args.query,
        index_path=index_path,
        top_k=args.top_k,
        snippet_chars=args.snippet_chars,
    )

    if args.json:
        print(dumps_json(payload))
        return 0

    results = retrieve_sections.rank_sections(sections, args.query, args.top_k)
    retrieve_sections.print_results(args.query, results, args.snippet_chars)
    return 0


def handle_eval(args: argparse.Namespace) -> int:
    index_path = resolve_existing_file(args.index, "index file")
    payload = run_eval_suite(index_path=index_path)

    if args.json:
        print(dumps_json(payload))
    else:
        print_eval_suite(payload)

    return 0 if payload["overall_status"] == "ok" else 1


def handle_round(args: argparse.Namespace) -> int:
    if args.skip_probe and args.skip_eval:
        raise SystemExit("At least one of --skip-probe / --skip-eval must be false.")
    if args.top_k <= 0:
        raise SystemExit("--top-k must be a positive integer")
    if args.snippet_chars <= 0:
        raise SystemExit("--snippet-chars must be a positive integer")

    queries = []
    if not args.skip_probe:
        queries = collect_queries(args.query, args.query_file)

    index_path = resolve_existing_file(args.index, "index file")
    payload = build_round_payload(
        queries=queries,
        index_path=index_path,
        top_k=args.top_k,
        snippet_chars=args.snippet_chars,
        skip_probe=args.skip_probe,
        skip_eval=args.skip_eval,
    )

    if args.json:
        print(dumps_json(payload))
    else:
        print_round_payload(payload)

    return 0 if payload["overall_status"] == "ok" else 1


def handle_build_index(args: argparse.Namespace) -> int:
    note_root = resolve_existing_directory(args.note_root, "note root")
    page_index_path = resolve_existing_file(args.page_index, "page index")
    source_root = (
        resolve_existing_directory(args.source_root, "source root")
        if args.source_root
        else None
    )
    output_path = resolve_build_output_path(args.output)

    payload = build_index_payload(
        note_root=note_root,
        page_index_path=page_index_path,
        source_root=source_root,
        include_unmapped_second_level_notes=args.include_unmapped_second_level_notes,
    )

    verification_payload = None
    if args.verify:
        target_ids = args.sections or DEFAULT_VERIFY_TARGETS
        verification_payload = collect_build_index_verification_payload(
            payload["sections"],
            target_ids,
        )

    write_output(output_path, payload)

    if args.json:
        summary = {
            "backend_dir": str(BACKEND_DIR),
            "output_path": str(output_path),
            "linked_sections_count": payload["linked_sections_count"],
            "note_sections_count": payload["note_sections_count"],
            "page_index_sections_count": payload["page_index_sections_count"],
            "unmapped_note_sections_count": payload["unmapped_note_sections_count"],
            "unmapped_page_index_sections_count": payload[
                "unmapped_page_index_sections_count"
            ],
            "verification": verification_payload,
        }
        print(dumps_json(summary))
        return 0

    print(
        f"Generated {payload['linked_sections_count']} linked sections -> "
        f"{display_path(output_path, BACKEND_DIR)}"
    )
    if args.verify:
        print_verification(payload["sections"], args.sections or DEFAULT_VERIFY_TARGETS)
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "answer": handle_answer,
        "retrieve": handle_retrieve,
        "eval": handle_eval,
        "round": handle_round,
        "build-index": handle_build_index,
    }

    sys.exit(handlers[args.command](args))
