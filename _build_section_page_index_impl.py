from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_VERIFY_TARGETS = [
    "3.2.1",
    "3.2.2",
    "10.2.1",
]

SECTION_HEADING_RE = re.compile(
    r"^#\s+([0-9]+(?:\.[0-9]+){1,2})\s+(.+?)\s*$",
    re.MULTILINE,
)
SECTION_FILENAME_RE = re.compile(r"^([0-9]+(?:\.[0-9]+){1,2})\s+(.+?)\.md$")
PAGE_INDEX_ROW_RE = re.compile(
    r"^\|\s*([0-9]+\.[0-9]+\.[0-9]+)\s+(.+?)\s*\|\s*([0-9]+)-([0-9]+)\s*\|\s*([0-9]+)-([0-9]+)\s*\|",
    re.MULTILINE,
)
INLINE_PDF_PAGE_RE = re.compile(r"\*\*PDF页码\*\*：\s*([0-9]+)-([0-9]+)")
SUMMARY_SECTION_TITLES = ("内容提要", "本章总结")
FILENAME_FALLBACK_SCOPES = (
    ("第五篇 代数系统/第12章 代数系统/", ("12.4.", "12.5.")),
    ("第五篇 代数系统/第13章 群/", ("13.2.", "13.3.")),
    ("第五篇 代数系统/第14章 环与域/", ("14.2.",)),
)


@dataclass(frozen=True)
class NoteSection:
    section_id: str
    title: str
    aliases: list[str]
    source_path: str
    content: str
    inline_pdf_page_start: int | None
    inline_pdf_page_end: int | None


@dataclass(frozen=True)
class PageIndexEntry:
    section_id: str
    indexed_title: str
    book_page_start: int
    book_page_end: int
    pdf_page_start: int
    pdf_page_end: int


def configure_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


def extract_frontmatter_and_body(text: str) -> tuple[str, str]:
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, re.DOTALL)
    if not match:
        return "", text
    return match.group(1), text[match.end() :]


def clean_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_aliases(frontmatter: str) -> list[str]:
    aliases: list[str] = []
    collecting_list = False

    for raw_line in frontmatter.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if collecting_list:
            if stripped.startswith("- "):
                aliases.append(clean_yaml_scalar(stripped[2:]))
                continue
            if stripped == "":
                continue
            if not raw_line.startswith(" "):
                collecting_list = False
            else:
                continue

        if not stripped.startswith("aliases:"):
            continue

        alias_value = stripped[len("aliases:") :].strip()
        if not alias_value:
            collecting_list = True
            continue

        if alias_value.startswith("[") and alias_value.endswith("]"):
            items = [
                clean_yaml_scalar(item.strip())
                for item in alias_value[1:-1].split(",")
                if item.strip()
            ]
            aliases.extend(items)
        else:
            aliases.append(clean_yaml_scalar(alias_value))

    return aliases


def first_nonempty_line(text: str) -> str:
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped:
            return stripped
    return ""


def parse_section_from_filename_fallback(
    note_path: Path,
    body: str,
) -> tuple[str, str, str] | None:
    filename_match = SECTION_FILENAME_RE.fullmatch(note_path.name)
    if not filename_match:
        return None

    section_id = filename_match.group(1).strip()
    title = filename_match.group(2).strip()
    note_path_posix = note_path.as_posix()
    if not any(
        note_path_posix.find(path_fragment) != -1
        and any(section_id.startswith(prefix) for prefix in prefixes)
        for path_fragment, prefixes in FILENAME_FALLBACK_SCOPES
    ):
        return None

    # Keep this compatibility shim scoped to the exact chapter/section groups
    # whose current note bodies omit the top-level heading but still belong to
    # the current default page-index corpus.
    if not first_nonempty_line(body).startswith("> [!abstract]"):
        return None

    return section_id, title, body.strip()


def normalize_markdown_content(
    body: str,
    note_path: Path,
) -> tuple[str, str, str]:
    match = SECTION_HEADING_RE.search(body)
    if not match:
        fallback = parse_section_from_filename_fallback(note_path, body)
        if fallback is None:
            raise ValueError("missing section heading")
        return fallback

    section_id = match.group(1).strip()
    title = match.group(2).strip()
    content = body[match.end() :].strip()
    return section_id, title, content


def parse_inline_pdf_page_range(body: str) -> tuple[int | None, int | None]:
    match = INLINE_PDF_PAGE_RE.search(body)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def parse_note_section(note_path: Path, vault_root: Path) -> NoteSection | None:
    text = note_path.read_text(encoding="utf-8")
    frontmatter, body = extract_frontmatter_and_body(text)

    try:
        section_id, title, content = normalize_markdown_content(body, note_path)
    except ValueError:
        return None

    inline_pdf_page_start, inline_pdf_page_end = parse_inline_pdf_page_range(body)

    return NoteSection(
        section_id=section_id,
        title=title,
        aliases=parse_aliases(frontmatter),
        source_path=note_path.relative_to(vault_root).as_posix(),
        content=content,
        inline_pdf_page_start=inline_pdf_page_start,
        inline_pdf_page_end=inline_pdf_page_end,
    )


def load_note_sections(note_root: Path, vault_root: Path) -> dict[str, NoteSection]:
    sections: dict[str, NoteSection] = {}

    for note_path in sorted(note_root.rglob("*.md")):
        section = parse_note_section(note_path, vault_root)
        if section is None:
            continue
        if section.section_id in sections:
            raise ValueError(f"duplicate note section id: {section.section_id}")
        sections[section.section_id] = section

    return sections


def parse_page_index(index_path: Path) -> dict[str, PageIndexEntry]:
    text = index_path.read_text(encoding="utf-8")
    entries: dict[str, PageIndexEntry] = {}

    for match in PAGE_INDEX_ROW_RE.finditer(text):
        section_id = match.group(1).strip()
        if section_id in entries:
            raise ValueError(f"duplicate page index section id: {section_id}")
        entries[section_id] = PageIndexEntry(
            section_id=section_id,
            indexed_title=match.group(2).strip(),
            book_page_start=int(match.group(3)),
            book_page_end=int(match.group(4)),
            pdf_page_start=int(match.group(5)),
            pdf_page_end=int(match.group(6)),
        )

    return entries


def build_records(
    note_sections: dict[str, NoteSection],
    page_index_entries: dict[str, PageIndexEntry],
    *,
    include_unmapped_second_level_notes: bool,
) -> list[dict[str, object]]:
    shared_section_ids = sorted(set(note_sections) & set(page_index_entries))
    linked_note_ids = set(shared_section_ids)
    records: list[dict[str, object]] = []

    for section_id in shared_section_ids:
        note = note_sections[section_id]
        index_entry = page_index_entries[section_id]
        records.append(
            {
                "section_id": section_id,
                "title": note.title,
                "indexed_title": index_entry.indexed_title,
                "aliases": note.aliases,
                "source_path": note.source_path,
                "book_page_start": index_entry.book_page_start,
                "book_page_end": index_entry.book_page_end,
                "pdf_page_start": index_entry.pdf_page_start,
                "pdf_page_end": index_entry.pdf_page_end,
                "content": note.content,
            }
        )

    if not include_unmapped_second_level_notes:
        return records

    # Compatibility-only fallback: some legacy notes carry inline PDF pages but do
    # not belong to the current page-index numbering system. Keep them opt-in so
    # the default backend corpus stays aligned with 页码索引.md.
    for section_id, note in sorted(note_sections.items()):
        if section_id in linked_note_ids:
            continue
        if section_id in page_index_entries:
            continue
        if section_id.count(".") != 1:
            continue
        if note.inline_pdf_page_start is None or note.inline_pdf_page_end is None:
            continue
        if any(marker in note.title for marker in SUMMARY_SECTION_TITLES):
            continue
        if any(
            other_section_id.startswith(f"{section_id}.")
            for other_section_id in note_sections
        ):
            continue

        linked_note_ids.add(section_id)
        records.append(
            {
                "section_id": section_id,
                "title": note.title,
                "indexed_title": note.title,
                "aliases": note.aliases,
                "source_path": note.source_path,
                "book_page_start": note.inline_pdf_page_start,
                "book_page_end": note.inline_pdf_page_end,
                "pdf_page_start": note.inline_pdf_page_start,
                "pdf_page_end": note.inline_pdf_page_end,
                "content": note.content,
            }
        )

    return records


def write_output(output_path: Path, payload: dict[str, object]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def print_verification(records: list[dict[str, object]], target_ids: list[str]) -> None:
    record_by_id = {record["section_id"]: record for record in records}
    missing = [target_id for target_id in target_ids if target_id not in record_by_id]
    if missing:
        raise SystemExit(f"missing target sections: {', '.join(missing)}")

    verification_payload = [
        {
            "section_id": record_by_id[target_id]["section_id"],
            "title": record_by_id[target_id]["title"],
            "aliases": record_by_id[target_id]["aliases"],
            "source_path": record_by_id[target_id]["source_path"],
            "pdf_page_start": record_by_id[target_id]["pdf_page_start"],
            "pdf_page_end": record_by_id[target_id]["pdf_page_end"],
        }
        for target_id in target_ids
    ]
    print(json.dumps(verification_payload, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a minimal section-to-page index for 离散数学 RAG backend."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "section_page_index.json",
        help="Where to write the generated JSON index.",
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

    backend_root = Path(__file__).resolve().parent
    book_root = backend_root.parents[1]
    vault_root = book_root.parents[1]
    note_root = book_root / "笔记"
    page_index_path = book_root / "页码索引.md"
    output_path = args.output if args.output.is_absolute() else vault_root / args.output

    note_sections = load_note_sections(note_root, vault_root)
    page_index_entries = parse_page_index(page_index_path)
    records = build_records(
        note_sections,
        page_index_entries,
        include_unmapped_second_level_notes=args.include_unmapped_second_level_notes,
    )
    linked_section_ids = {record["section_id"] for record in records}

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note_root": note_root.relative_to(vault_root).as_posix(),
        "page_index_path": page_index_path.relative_to(vault_root).as_posix(),
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
        f"{output_path.relative_to(vault_root).as_posix()}"
    )

    if args.verify:
        target_ids = args.sections or DEFAULT_VERIFY_TARGETS
        print_verification(records, target_ids)


if __name__ == "__main__":
    main()
