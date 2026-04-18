from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from retrieve_sections import (
    SectionRecord,
    build_query_features,
    build_snippet,
    compact_text,
    load_sections,
    rank_sections,
)


CALLOUT_HEADER_RE = re.compile(r"^>\s*\[!([^\]]+)\](?:\s*(.*))?$")
ENUMERATION_PREFIX_RE = re.compile(r"^(?:\(?\d+\)?[.)、]?|（\d+）)")
EMPHASIS_RE = re.compile(r"[*`_~]+")
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]|\[\[([^\]]+)\]\]")
LATEX_RE = re.compile(r"\$(.+?)\$")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；])\s*")


@dataclass(frozen=True)
class CalloutBlock:
    callout_type: str
    body_lines: tuple[str, ...]


def strip_markdown(text: str) -> str:
    text = WIKILINK_RE.sub(lambda match: match.group(2) or match.group(3) or match.group(1), text)
    text = LATEX_RE.sub(lambda match: match.group(1), text)
    text = EMPHASIS_RE.sub("", text)
    text = re.sub(r"\\([()])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def iter_callout_blocks(content: str) -> Iterable[CalloutBlock]:
    lines = content.splitlines()
    index = 0

    while index < len(lines):
        header_match = CALLOUT_HEADER_RE.match(lines[index].strip())
        if header_match is None:
            index += 1
            continue

        callout_type = header_match.group(1).lower()
        body_lines: list[str] = []
        index += 1

        while index < len(lines):
            stripped = lines[index].strip()

            if not stripped:
                if body_lines and body_lines[-1] != "":
                    body_lines.append("")
                index += 1
                continue

            if stripped.startswith("---") or stripped.startswith("#"):
                break

            if CALLOUT_HEADER_RE.match(stripped):
                break

            if not stripped.startswith(">"):
                break

            body_lines.append(stripped[1:].strip())
            index += 1

        yield CalloutBlock(callout_type=callout_type, body_lines=tuple(body_lines))


def summarize_lines(lines: Iterable[str], max_lines: int = 2) -> str:
    summary_parts: list[str] = []

    for raw_line in lines:
        line = strip_markdown(raw_line)
        if not line:
            continue

        if line.startswith("[!") or line == "---":
            continue

        if line.startswith("- "):
            line = line[2:].strip()

        summary_parts.append(line)
        if len(summary_parts) >= max_lines:
            break

    return " ".join(summary_parts).strip()


def contains_direct_definition(text: str, targets: Iterable[str]) -> bool:
    compact = compact_text(text)
    for target in targets:
        if not target:
            continue
        if (
            f"称为{target}" in compact
            or f"{target}是" in compact
            or f"{target}指" in compact
            or f"{target}可定义为" in compact
        ):
            return True
    return False


def starts_with_enumeration(text: str) -> bool:
    return bool(ENUMERATION_PREFIX_RE.match(text))


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]


def refine_answer_text(text: str, targets: Iterable[str], answer_chars: int) -> str:
    sentences = split_sentences(text)
    if not sentences:
        return text

    direct_indexes = [
        index for index, sentence in enumerate(sentences) if contains_direct_definition(sentence, targets)
    ]
    if direct_indexes:
        start_index = direct_indexes[0]
        selected = [sentences[start_index]]
        if (
            start_index == 0
            and len(sentences) > 1
            and len(selected[0]) + 1 + len(sentences[1]) <= answer_chars
        ):
            selected.append(sentences[1])
        return " ".join(selected)

    informative_indexes = [
        index
        for index, sentence in enumerate(sentences)
        if any(target and target in compact_text(sentence) for target in targets)
        and "是" in sentence
    ]
    if informative_indexes:
        return sentences[informative_indexes[0]]

    return text


def score_candidate(
    block: CalloutBlock,
    text: str,
    section: SectionRecord,
    query: str,
) -> float:
    features = build_query_features(query)
    targets = [features.simplified, features.compact, section.title_compact]
    compact = compact_text(text)

    type_score = {
        "abstract": 48.0 if features.definition_intent else 28.0,
        "definition": 44.0 if features.definition_intent else 24.0,
        "summary": 18.0,
        "important": 16.0,
        "note": 12.0,
    }.get(block.callout_type, 8.0)

    score = type_score

    if contains_direct_definition(text, targets):
        score += 42.0

    if any(target and target in compact for target in targets):
        score += 16.0

    if block.callout_type == "definition" and starts_with_enumeration(text):
        score -= 22.0

    return score


def extract_concise_answer(section: SectionRecord, query: str, answer_chars: int) -> str:
    features = build_query_features(query)
    targets = [features.simplified, features.compact, section.title_compact]
    candidates: list[tuple[float, str]] = []

    for block in iter_callout_blocks(section.content):
        candidate_text = summarize_lines(block.body_lines)
        if not candidate_text:
            continue
        candidates.append((score_candidate(block, candidate_text, section, query), candidate_text))

    if candidates:
        candidates.sort(key=lambda item: (-item[0], len(item[1])))
        answer = refine_answer_text(candidates[0][1], targets, answer_chars)
    else:
        answer = build_snippet(section.content, answer_chars)

    answer = re.sub(r"\s+", " ", answer).strip()
    if len(answer) <= answer_chars:
        return answer

    return answer[: max(answer_chars - 1, 0)].rstrip() + "…"


def build_answer_payload(
    sections: list[SectionRecord],
    query: str,
    top_k: int = 3,
    answer_chars: int = 220,
) -> dict[str, object]:
    ranked = rank_sections(sections, query, top_k)
    if not ranked:
        return {
            "query": query,
            "answer": "",
            "section_id": None,
            "title": None,
            "source_path": None,
            "pdf_page_start": None,
            "pdf_page_end": None,
            "supporting_matches": [],
        }

    top_result = ranked[0]
    answer = extract_concise_answer(top_result.section, query, answer_chars)

    return {
        "query": query,
        "answer": answer,
        "section_id": top_result.section.section_id,
        "title": top_result.section.title,
        "source_path": top_result.section.source_path,
        "pdf_page_start": top_result.section.pdf_page_start,
        "pdf_page_end": top_result.section.pdf_page_end,
        "supporting_matches": [
            result.to_payload(query, snippet_chars=120) for result in ranked
        ],
    }


def print_answer(payload: dict[str, object]) -> None:
    print(f"query: {payload['query']}")

    if not payload["answer"]:
        print("answer: 未找到足够相关的小节。")
        return

    print(f"answer: {payload['answer']}")
    print(f"section: [{payload['section_id']}] {payload['title']}")
    print(f"source: {payload['source_path']}")
    print(f"pdf: {payload['pdf_page_start']}-{payload['pdf_page_end']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a concise answer from the top retrieved section."
    )
    parser.add_argument("query", help="Natural-language question to answer.")
    parser.add_argument(
        "--index",
        type=Path,
        default=Path(__file__).resolve().parent / "section_page_index.json",
        help="Path to section_page_index.json.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="How many retrieved sections to consider.",
    )
    parser.add_argument(
        "--answer-chars",
        type=int,
        default=220,
        help="Maximum answer length in characters.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the answer payload as JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top_k <= 0:
        raise SystemExit("--top-k must be a positive integer")
    if args.answer_chars <= 0:
        raise SystemExit("--answer-chars must be a positive integer")

    sections = load_sections(args.index.resolve())
    payload = build_answer_payload(
        sections=sections,
        query=args.query,
        top_k=args.top_k,
        answer_chars=args.answer_chars,
    )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print_answer(payload)


if __name__ == "__main__":
    main()
