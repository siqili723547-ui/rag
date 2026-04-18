from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from _build_section_page_index_impl import (
    DEFAULT_VERIFY_TARGETS,
    build_records,
    configure_stdio,
    load_note_sections,
    parse_page_index,
    print_verification,
    write_output,
)


def display_path(path: Path, base: Path) -> str:
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(base.resolve()).as_posix()
    except ValueError:
        return resolved_path.as_posix()


def default_source_root(note_root: Path, page_index_path: Path) -> Path:
    common_path = os.path.commonpath(
        [str(note_root.resolve()), str(page_index_path.resolve())]
    )
    return Path(common_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a minimal section-to-page index for the standalone RAG project."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "section_page_index.json",
        help="Where to write the generated JSON index.",
    )
    parser.add_argument(
        "--note-root",
        type=Path,
        required=True,
        help="Path to the external note corpus root.",
    )
    parser.add_argument(
        "--page-index",
        type=Path,
        required=True,
        help="Path to the external page-index markdown file.",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        help=(
            "Optional shared root used to relativize note_root, page_index_path, "
            "and note source paths in the generated JSON."
        ),
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Print selected section mappings after building the JSON index.",
    )
    parser.add_argument(
        "--section",
        action="append",
        dest="sections",
        default=[],
        help="Section id to verify. Can be passed multiple times.",
    )
    parser.add_argument(
        "--include-unmapped-second-level-notes",
        action="store_true",
        help=(
            "Include unmatched second-level notes that self-report inline PDF "
            "pages. Disabled by default to keep the generated index aligned "
            "with 页码索引.md."
        ),
    )
    return parser.parse_args()


def main() -> None:
    configure_stdio()
    args = parse_args()

    project_root = Path(__file__).resolve().parent
    note_root = args.note_root.resolve()
    page_index_path = args.page_index.resolve()
    source_root = args.source_root.resolve() if args.source_root else None
    output_path = args.output if args.output.is_absolute() else project_root / args.output

    if not note_root.exists():
        raise SystemExit(f"note root not found: {note_root}")
    if not page_index_path.exists():
        raise SystemExit(f"page index not found: {page_index_path}")
    if source_root is not None and not source_root.exists():
        raise SystemExit(f"source root not found: {source_root}")

    resolved_source_root = source_root or default_source_root(note_root, page_index_path)

    note_sections = load_note_sections(note_root, resolved_source_root)
    page_index_entries = parse_page_index(page_index_path)
    records = build_records(
        note_sections,
        page_index_entries,
        include_unmapped_second_level_notes=args.include_unmapped_second_level_notes,
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
    write_output(output_path, payload)

    print(
        f"Generated {len(records)} linked sections -> "
        f"{display_path(output_path, project_root)}"
    )

    if args.verify:
        target_ids = args.sections or DEFAULT_VERIFY_TARGETS
        print_verification(records, target_ids)


if __name__ == "__main__":
    main()
