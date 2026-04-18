from __future__ import annotations

import json
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
BUILD_INDEX_FIXTURE_DIR = BACKEND_DIR / "test_fixtures" / "build_index"
SOURCE_ROOT = BUILD_INDEX_FIXTURE_DIR / "vault"
NOTE_ROOT = SOURCE_ROOT / "notes"
PAGE_INDEX_PATH = SOURCE_ROOT / "page_index.md"
EXPECTED_INDEX_PATH = BUILD_INDEX_FIXTURE_DIR / "expected_section_page_index.json"


def build_index_fixture_args() -> list[str]:
    return [
        "--note-root",
        str(NOTE_ROOT),
        "--page-index",
        str(PAGE_INDEX_PATH),
        "--source-root",
        str(SOURCE_ROOT),
    ]


def load_expected_index_payload() -> dict[str, object]:
    return json.loads(EXPECTED_INDEX_PATH.read_text(encoding="utf-8"))


def build_expected_verification_payload(section_ids: list[str]) -> list[dict[str, object]]:
    records_by_id = {
        record["section_id"]: record
        for record in load_expected_index_payload()["sections"]
    }
    return [
        {
            "section_id": records_by_id[section_id]["section_id"],
            "title": records_by_id[section_id]["title"],
            "aliases": records_by_id[section_id]["aliases"],
            "source_path": records_by_id[section_id]["source_path"],
            "pdf_page_start": records_by_id[section_id]["pdf_page_start"],
            "pdf_page_end": records_by_id[section_id]["pdf_page_end"],
        }
        for section_id in section_ids
    ]
