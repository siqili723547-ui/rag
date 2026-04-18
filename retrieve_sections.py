from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_VERIFY_CASES_PATH = (
    Path(__file__).resolve().parent / "section_retrieval_eval_cases.json"
)

SECTION_ID_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
QUERY_FILLER_PATTERNS = [
    "请问",
    "帮我",
    "解释一下",
    "解释",
    "介绍一下",
    "介绍",
    "什么叫",
    "什么是",
    "是啥",
    "定义是什么",
    "是什么意思",
    "如何理解",
    "怎么理解",
    "有哪些",
    "有哪几种",
    "为什么",
]
TEXT_CHUNK_RE = re.compile(r"[A-Za-z0-9.+#=_-]+|[\u4e00-\u9fff]+")
PUNCTUATION_RE = re.compile(r"[^\w\s\u4e00-\u9fff]+")
DEFINITION_SECTION_MARKERS = ("引入与定义", "定义")
DEFINITION_DISTRACTOR_MARKERS = ("判定", "应用", "难点")
EARLY_OPENING_TARGET_POSITION = 100
DEFINITION_PARTIAL_OVERLAP_ONLY_PENALTY = 33.0


@dataclass(frozen=True)
class QueryFeatures:
    raw: str
    compact: str
    simplified: str
    terms: tuple[str, ...]
    section_id: str | None
    definition_intent: bool


@dataclass(frozen=True)
class SectionRecord:
    section_id: str
    title: str
    indexed_title: str
    aliases: tuple[str, ...]
    source_path: str
    pdf_page_start: int
    pdf_page_end: int
    content: str
    title_compact: str
    indexed_title_compact: str
    alias_compacts: tuple[str, ...]
    content_compact: str
    opening_content_compact: str
    has_opening_definition_block: bool


@dataclass(frozen=True)
class RankedResult:
    score: float
    section: SectionRecord
    reasons: tuple[str, ...]

    def to_payload(self, query: str, snippet_chars: int) -> dict[str, object]:
        return {
            "query": query,
            "score": round(self.score, 3),
            "section_id": self.section.section_id,
            "title": self.section.title,
            "source_path": self.section.source_path,
            "pdf_page_start": self.section.pdf_page_start,
            "pdf_page_end": self.section.pdf_page_end,
            "match_reasons": list(self.reasons),
            "snippet": build_snippet(self.section.content, snippet_chars),
        }


@dataclass(frozen=True)
class VerificationCase:
    query: str
    expected_section_id: str


@dataclass(frozen=True)
class VerificationResult:
    case: VerificationCase
    results: tuple[RankedResult, ...]
    matched_rank: int | None

    @property
    def top1_hit(self) -> bool:
        return self.matched_rank == 1

    @property
    def top3_hit(self) -> bool:
        return self.matched_rank is not None and self.matched_rank <= 3

    @property
    def top_k_hit(self) -> bool:
        return self.matched_rank is not None

    def to_payload(self, top_k: int, snippet_chars: int) -> dict[str, object]:
        return {
            "query": self.case.query,
            "expected_section_id": self.case.expected_section_id,
            "matched_rank": self.matched_rank,
            "top1_hit": self.top1_hit,
            "top3_hit": self.top3_hit,
            f"top{top_k}_hit": self.top_k_hit,
            "results": [
                result.to_payload(self.case.query, snippet_chars)
                for result in self.results
            ],
        }


def configure_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower().strip()


def compact_text(text: str) -> str:
    normalized = normalize_text(text)
    return re.sub(r"\s+", "", normalized)


def simplify_query(text: str) -> str:
    simplified = normalize_text(text)
    simplified = simplified.replace("？", " ").replace("?", " ")
    simplified = PUNCTUATION_RE.sub(" ", simplified)

    for filler in QUERY_FILLER_PATTERNS:
        simplified = simplified.replace(filler, " ")

    simplified = simplified.replace("一下", " ")
    simplified = simplified.replace("一下子", " ")
    simplified = simplified.replace("呀", " ")
    simplified = simplified.replace("啊", " ")
    simplified = re.sub(r"\s+", " ", simplified).strip()
    return simplified


def cjk_ngrams(text: str) -> set[str]:
    length = len(text)
    if length == 0:
        return set()
    if length == 1:
        return {text}

    grams: set[str] = {text}
    min_n = 2
    max_n = min(6, length)
    for n in range(min_n, max_n + 1):
        for start in range(0, length - n + 1):
            grams.add(text[start : start + n])

    if length <= 2:
        grams.update(text)
    return grams


def extract_terms(text: str) -> set[str]:
    terms: set[str] = set()

    for chunk in TEXT_CHUNK_RE.findall(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
            terms.update(cjk_ngrams(chunk))
            continue
        terms.add(chunk)

    return {term for term in terms if term}


def build_query_features(query: str) -> QueryFeatures:
    raw = normalize_text(query)
    section_id = raw if SECTION_ID_RE.fullmatch(raw) else None
    simplified = "" if section_id else simplify_query(query)
    terms = {raw} if section_id else (extract_terms(raw) | extract_terms(simplified))
    ordered_terms = tuple(sorted(terms, key=lambda item: (-len(item), item)))
    definition_intent = any(
        marker in raw
        for marker in ("什么是", "什么叫", "定义", "是什么意思", "解释", "介绍")
    )
    return QueryFeatures(
        raw=query,
        compact=compact_text(raw),
        simplified=compact_text(simplified),
        terms=ordered_terms,
        section_id=section_id,
        definition_intent=definition_intent,
    )


def load_sections(index_path: Path) -> list[SectionRecord]:
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    records: list[SectionRecord] = []

    for item in payload["sections"]:
        aliases = tuple(item.get("aliases", []))
        opening_content_compact, has_opening_definition_block = extract_opening_content(
            item["content"]
        )
        records.append(
            SectionRecord(
                section_id=item["section_id"],
                title=item["title"],
                indexed_title=item["indexed_title"],
                aliases=aliases,
                source_path=item["source_path"],
                pdf_page_start=item["pdf_page_start"],
                pdf_page_end=item["pdf_page_end"],
                content=item["content"],
                title_compact=compact_text(item["title"]),
                indexed_title_compact=compact_text(item["indexed_title"]),
                alias_compacts=tuple(compact_text(alias) for alias in aliases),
                content_compact=compact_text(item["content"]),
                opening_content_compact=opening_content_compact,
                has_opening_definition_block=has_opening_definition_block,
            )
        )

    return records


def term_weight(term: str) -> float:
    if SECTION_ID_RE.fullmatch(term):
        return 20.0
    if len(term) == 1:
        return 0.5
    return min(1.0 + math.log(len(term) + 1, 2), 4.0)


def field_contains(field: str, term: str) -> bool:
    return bool(term) and term in field


def field_has_any_marker(field: str, markers: tuple[str, ...]) -> bool:
    return any(marker in field for marker in markers)


def is_single_cjk_character(text: str) -> bool:
    return len(text) == 1 and "\u4e00" <= text <= "\u9fff"


def iter_opening_lines(content: str) -> Iterable[str]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    heading_count = 0

    for line in lines:
        if line.startswith("## "):
            heading_count += 1
            if heading_count >= 2:
                break

        yield line


def extract_opening_content(content: str) -> tuple[str, bool]:
    opening_lines: list[str] = []
    has_definition_block = False

    for line in iter_opening_lines(content):
        opening_lines.append(line)
        if "[!definition]" in line:
            has_definition_block = True
        if len(opening_lines) >= 24:
            break

    return compact_text("\n".join(opening_lines)), has_definition_block


def matches_definition_target(target: str, record: SectionRecord) -> bool:
    if not target:
        return False
    if record.title_compact.startswith(target):
        return True
    if record.indexed_title_compact.startswith(target):
        return True
    return any(alias == target or alias.startswith(target) for alias in record.alias_compacts)


def definition_target_in_title(target: str, record: SectionRecord) -> bool:
    if not target:
        return False
    return field_contains(record.title_compact, target) or field_contains(
        record.indexed_title_compact,
        target,
    )


def definition_target_in_alias(target: str, record: SectionRecord) -> bool:
    if not target:
        return False
    return any(alias == target or alias.startswith(target) for alias in record.alias_compacts)


def definition_target_in_opening_content(target: str, record: SectionRecord) -> bool:
    if not target:
        return False
    return field_contains(record.opening_content_compact, target)


def iter_opening_definition_body_lines(content: str) -> Iterable[str]:
    in_definition_block = False

    for line in iter_opening_lines(content):
        if "[!definition]" in line:
            in_definition_block = True
            continue

        if not in_definition_block:
            continue

        if line.startswith("## "):
            break

        if line.startswith("> [!") and "[!definition]" not in line:
            in_definition_block = False
            continue

        if not line.startswith(">"):
            in_definition_block = False
            continue

        yield line


def definition_target_in_opening_definition_body(target: str, record: SectionRecord) -> bool:
    if not target:
        return False
    return any(
        field_contains(compact_text(line), target)
        for line in iter_opening_definition_body_lines(record.content)
    )


def definition_target_in_opening_definition_sentence(
    target: str,
    record: SectionRecord,
) -> bool:
    if not target:
        return False

    cue_patterns = (
        f"称为{target}",
        f"叫做{target}",
        f"叫作{target}",
        f"记为{target}",
        f"记作{target}",
        f"{target}是",
    )
    titled_as_phrase = f"为{target}"

    for line in iter_opening_definition_body_lines(record.content):
        compact_line = compact_text(re.sub(r"[*`_~]+", "", line))
        if not field_contains(compact_line, target):
            continue
        if any(pattern in compact_line for pattern in cue_patterns):
            return True
        titled_as_index = compact_line.rfind(titled_as_phrase)
        if titled_as_index != -1 and "称" in compact_line[:titled_as_index]:
            return True

    return False


def definition_target_has_pre_definition_opening_mention(
    target: str,
    record: SectionRecord,
) -> bool:
    if not target:
        return False

    for line in iter_opening_lines(record.content):
        if "[!definition]" in line:
            break
        if line.startswith("#"):
            continue
        if field_contains(compact_text(line), target):
            return True

    return False


def definition_target_opening_bonus(target: str, record: SectionRecord) -> float:
    if not target:
        return 0.0

    if not definition_target_in_opening_content(target, record):
        return 0.0
    return 24.0


def definition_target_in_opening_heading(target: str, record: SectionRecord) -> bool:
    if not target:
        return False
    return any(
        line.startswith("#") and field_contains(compact_text(line), target)
        for line in iter_opening_lines(record.content)
    )


def definition_target_has_early_opening_hit(target: str, record: SectionRecord) -> bool:
    if not target:
        return False
    position = record.opening_content_compact.find(target)
    return 0 <= position <= EARLY_OPENING_TARGET_POSITION


def score_record(features: QueryFeatures, record: SectionRecord) -> RankedResult | None:
    score = 0.0
    reasons: list[str] = []
    definition_target = features.simplified or features.compact

    if features.section_id == record.section_id:
        score += 200.0
        reasons.append("section_id exact")

    phrase_candidates = [features.compact]
    if features.simplified and features.simplified not in phrase_candidates:
        phrase_candidates.append(features.simplified)

    for phrase in phrase_candidates:
        if not phrase:
            continue
        single_char_definition_phrase = (
            features.definition_intent
            and phrase == features.simplified
            and is_single_cjk_character(phrase)
        )

        if phrase == record.title_compact:
            score += 120.0
            reasons.append("title exact")
        elif record.title_compact.startswith(phrase):
            score += 92.0
            reasons.append("title starts with query")
        elif not single_char_definition_phrase and field_contains(
            record.title_compact,
            phrase,
        ):
            score += 80.0
            reasons.append("title contains query")

        if phrase == record.indexed_title_compact:
            score += 110.0
            reasons.append("indexed_title exact")
        elif record.indexed_title_compact.startswith(phrase):
            score += 82.0
            reasons.append("indexed_title starts with query")
        elif not single_char_definition_phrase and field_contains(
            record.indexed_title_compact,
            phrase,
        ):
            score += 70.0
            reasons.append("indexed_title contains query")

        alias_exact = any(phrase == alias for alias in record.alias_compacts)
        alias_starts = any(alias.startswith(phrase) for alias in record.alias_compacts)
        alias_contains = (
            not single_char_definition_phrase
            and any(field_contains(alias, phrase) for alias in record.alias_compacts)
        )
        if alias_exact:
            score += 100.0
            reasons.append("alias exact")
        elif alias_starts:
            score += 74.0
            reasons.append("alias starts with query")
        elif alias_contains:
            score += 65.0
            reasons.append("alias contains query")

        if field_contains(record.content_compact, phrase):
            score += 18.0
            reasons.append("content contains query")

    matched_title_terms = 0
    matched_alias_terms = 0
    matched_content_terms = 0

    for term in features.terms:
        weight = term_weight(term)
        matched_any = False

        if field_contains(record.title_compact, term):
            score += 12.0 * weight
            matched_title_terms += 1
            matched_any = True

        if field_contains(record.indexed_title_compact, term):
            score += 10.0 * weight
            matched_any = True

        if any(field_contains(alias, term) for alias in record.alias_compacts):
            score += 9.0 * weight
            matched_alias_terms += 1
            matched_any = True

        if field_contains(record.content_compact, term):
            score += 1.8 * weight
            matched_content_terms += 1
            matched_any = True

        if matched_any and term == record.section_id:
            score += 40.0

    if matched_title_terms:
        score += min(15.0, matched_title_terms * 3.0)
    if matched_alias_terms:
        score += min(12.0, matched_alias_terms * 2.5)
    if matched_content_terms and matched_title_terms:
        score += 6.0
    if features.definition_intent:
        single_char_definition_target = is_single_cjk_character(definition_target)
        definition_target_matched = matches_definition_target(definition_target, record)
        definition_target_matches_title = definition_target_in_title(
            definition_target,
            record,
        )
        definition_target_matches_alias = definition_target_in_alias(
            definition_target,
            record,
        )
        definition_target_matches_opening_content = definition_target_in_opening_content(
            definition_target,
            record,
        )
        has_definition_markers = field_has_any_marker(
            record.title_compact,
            DEFINITION_SECTION_MARKERS,
        ) or field_has_any_marker(
            record.indexed_title_compact,
            DEFINITION_SECTION_MARKERS,
        )
        has_distractor_markers = field_has_any_marker(
            record.title_compact,
            DEFINITION_DISTRACTOR_MARKERS,
        ) or field_has_any_marker(
            record.indexed_title_compact,
            DEFINITION_DISTRACTOR_MARKERS,
        )

        if definition_target_matched and has_definition_markers:
            score += 212.0
            reasons.append("definition-section priority")

        # When the query concept lives in aliases/body instead of the section title,
        # give the actual definition page a small extra nudge over sibling pages.
        if (
            has_definition_markers
            and not definition_target_matches_title
            and definition_target_matches_alias
        ):
            score += 36.0
            reasons.append("definition-alias bridge")

        # When title/aliases miss the concept, prefer pages whose opening block is
        # already introducing or defining that concept, without turning this into
        # a general body-text boost.
        if (
            record.has_opening_definition_block
            and not has_distractor_markers
            and not definition_target_matches_title
            and not definition_target_matches_alias
            and definition_target_matches_opening_content
        ):
            opening_definition_body_match = definition_target_in_opening_definition_body(
                definition_target,
                record,
            )
            opening_definition_sentence_match = (
                definition_target_in_opening_definition_sentence(
                    definition_target,
                    record,
                )
            )
            pre_definition_opening_mention = (
                definition_target_has_pre_definition_opening_mention(
                    definition_target,
                    record,
                )
            )
            score += definition_target_opening_bonus(definition_target, record)
            reasons.append("definition-content bridge")

            if opening_definition_sentence_match:
                score += 18.0
                reasons.append("definition-content definition sentence")

            if pre_definition_opening_mention and not opening_definition_body_match:
                score -= 12.0
                reasons.append("definition-content mention-only penalty")

            if definition_target_in_opening_heading(definition_target, record):
                score += 12.0
                reasons.append("definition-content heading anchor")

            if (
                definition_target_has_early_opening_hit(definition_target, record)
                and not (
                    pre_definition_opening_mention
                    and not opening_definition_body_match
                )
            ):
                score += 6.0
                reasons.append("definition-content early anchor")

            if single_char_definition_target and not opening_definition_sentence_match:
                score -= 60.0
                reasons.append("definition-content single-char weak-match penalty")

        if definition_target_matched and has_distractor_markers:
            score -= 140.0
            reasons.append("definition-intent sibling penalty")

    if (
        features.definition_intent
        and len(definition_target) >= 2
        and not reasons
    ):
        score -= DEFINITION_PARTIAL_OVERLAP_ONLY_PENALTY
        reasons.append("definition-intent partial-overlap penalty")

    if score <= 0:
        return None

    unique_reasons = tuple(dict.fromkeys(reasons))
    return RankedResult(score=score, section=record, reasons=unique_reasons)


def rank_sections(
    sections: Iterable[SectionRecord],
    query: str,
    top_k: int,
) -> list[RankedResult]:
    features = build_query_features(query)
    section_list = list(sections)

    if features.section_id is not None:
        for record in section_list:
            if record.section_id == features.section_id:
                exact_result = score_record(features, record)
                return [exact_result] if exact_result is not None else []

    ranked: list[RankedResult] = []

    for record in section_list:
        result = score_record(features, record)
        if result is not None:
            ranked.append(result)

    ranked.sort(
        key=lambda item: (
            -item.score,
            item.section.pdf_page_start,
            item.section.section_id,
        )
    )
    return ranked[:top_k]


def build_snippet(content: str, limit: int) -> str:
    plain = re.sub(r">\s*\[![^\]]+\]\s*", " ", content)
    plain = re.sub(r"\[\[[^\]]+\]\]", " ", plain)
    plain = re.sub(r"[#>*`|]+", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    if len(plain) <= limit:
        return plain
    return plain[: max(limit - 1, 0)] + "…"


def print_results(query: str, results: list[RankedResult], snippet_chars: int) -> None:
    if not results:
        print(f"query: {query}")
        print("no matches")
        return

    print(f"query: {query}")
    for index, result in enumerate(results, start=1):
        payload = result.to_payload(query, snippet_chars)
        print(
            f"{index}. [{payload['section_id']}] {payload['title']} "
            f"(score={payload['score']})"
        )
        print(f"   source: {payload['source_path']}")
        print(f"   pdf: {payload['pdf_page_start']}-{payload['pdf_page_end']}")
        print(f"   reasons: {', '.join(payload['match_reasons']) or 'token overlap'}")
        print(f"   snippet: {payload['snippet']}")


def load_verification_cases(cases_path: Path) -> list[VerificationCase]:
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    raw_cases = payload["cases"] if isinstance(payload, dict) else payload

    cases: list[VerificationCase] = []
    for item in raw_cases:
        query = item.get("query", "").strip()
        expected_section_id = item.get("expected_section_id", "").strip()
        if not query or not expected_section_id:
            raise SystemExit(
                f"invalid verification case in {cases_path}: "
                f"{json.dumps(item, ensure_ascii=False)}"
            )
        cases.append(
            VerificationCase(
                query=query,
                expected_section_id=expected_section_id,
            )
        )

    if not cases:
        raise SystemExit(f"no verification cases found in {cases_path}")

    return cases


def evaluate_verification_cases(
    sections: list[SectionRecord],
    cases: Iterable[VerificationCase],
    top_k: int,
) -> list[VerificationResult]:
    verification_results: list[VerificationResult] = []

    for case in cases:
        ranked = tuple(rank_sections(sections, case.query, top_k))
        matched_rank = next(
            (
                index
                for index, result in enumerate(ranked, start=1)
                if result.section.section_id == case.expected_section_id
            ),
            None,
        )
        verification_results.append(
            VerificationResult(
                case=case,
                results=ranked,
                matched_rank=matched_rank,
            )
        )

    return verification_results


def build_verification_summary(
    verification_results: list[VerificationResult],
    top_k: int,
) -> dict[str, object]:
    case_count = len(verification_results)
    top1_hits = sum(result.top1_hit for result in verification_results)
    top3_hits = sum(result.top3_hit for result in verification_results)
    top_k_hits = sum(result.top_k_hit for result in verification_results)

    def hit_rate(hit_count: int) -> float:
        if case_count == 0:
            return 0.0
        return round(hit_count / case_count, 3)

    return {
        "case_count": case_count,
        "top_k": top_k,
        "top1_hits": top1_hits,
        "top3_hits": top3_hits,
        "top_k_hits": top_k_hits,
        "top1_hit_rate": hit_rate(top1_hits),
        "top3_hit_rate": hit_rate(top3_hits),
        "top_k_hit_rate": hit_rate(top_k_hits),
    }


def build_verification_payload(
    verification_results: list[VerificationResult],
    top_k: int,
    snippet_chars: int,
) -> dict[str, object]:
    return {
        "summary": build_verification_summary(verification_results, top_k),
        "cases": [
            result.to_payload(top_k=top_k, snippet_chars=snippet_chars)
            for result in verification_results
        ],
    }


def print_verification_report(
    verification_results: list[VerificationResult],
    top_k: int,
    snippet_chars: int,
) -> None:
    for result in verification_results:
        print(f"query: {result.case.query}")
        print(f"expected_section_id: {result.case.expected_section_id}")
        print(
            "matched_rank: "
            + (str(result.matched_rank) if result.matched_rank is not None else "miss")
        )
        print(f"top1_hit: {'yes' if result.top1_hit else 'no'}")
        print(f"top3_hit: {'yes' if result.top3_hit else 'no'}")
        print(f"top{top_k}_hit: {'yes' if result.top_k_hit else 'no'}")

        if not result.results:
            print("top_results: none")
            print("")
            continue

        print("top_results:")
        for index, ranked_result in enumerate(result.results, start=1):
            payload = ranked_result.to_payload(result.case.query, snippet_chars)
            print(
                f"  {index}. [{payload['section_id']}] {payload['title']} "
                f"(score={payload['score']})"
            )
            print(f"     source: {payload['source_path']}")
            print(f"     pdf: {payload['pdf_page_start']}-{payload['pdf_page_end']}")
            print(
                "     reasons: "
                + (", ".join(payload["match_reasons"]) or "token overlap")
            )
            print(f"     snippet: {payload['snippet']}")
        print("")

    summary = build_verification_summary(verification_results, top_k)
    print("summary:")
    print(f"  cases: {summary['case_count']}")
    print(
        f"  top1: {summary['top1_hits']}/{summary['case_count']} "
        f"({summary['top1_hit_rate']:.1%})"
    )
    print(
        f"  top3: {summary['top3_hits']}/{summary['case_count']} "
        f"({summary['top3_hit_rate']:.1%})"
    )
    print(
        f"  top{top_k}: {summary['top_k_hits']}/{summary['case_count']} "
        f"({summary['top_k_hit_rate']:.1%})"
    )


def collect_verification_failures(
    verification_results: Iterable[VerificationResult],
) -> list[str]:
    failures: list[str] = []
    for result in verification_results:
        if result.top_k_hit:
            continue
        actual_top_ids = [ranked.section.section_id for ranked in result.results]
        failures.append(
            f"query={result.case.query!r} expected={result.case.expected_section_id} "
            f"actual_top_ids={actual_top_ids}"
        )
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retrieve relevant note sections from section_page_index.json."
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Natural-language query to retrieve relevant sections for.",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=Path(__file__).resolve().parent / "section_page_index.json",
        help="Path to section_page_index.json.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="How many top-ranked sections to return.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the retrieval result as JSON.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run the fixed retrieval verification cases.",
    )
    parser.add_argument(
        "--verify-cases",
        type=Path,
        default=DEFAULT_VERIFY_CASES_PATH,
        help="Path to the fixed retrieval verification cases JSON file.",
    )
    parser.add_argument(
        "--snippet-chars",
        type=int,
        default=120,
        help="Maximum snippet length in characters.",
    )
    return parser.parse_args()


def main() -> None:
    configure_stdio()
    args = parse_args()

    if args.top_k <= 0:
        raise SystemExit("--top-k must be a positive integer")

    index_path = args.index.resolve()
    sections = load_sections(index_path)

    if args.verify:
        verify_cases_path = args.verify_cases.resolve()
        verification_cases = load_verification_cases(verify_cases_path)
        verification_results = evaluate_verification_cases(
            sections=sections,
            cases=verification_cases,
            top_k=args.top_k,
        )

        if args.json:
            payload = build_verification_payload(
                verification_results=verification_results,
                top_k=args.top_k,
                snippet_chars=args.snippet_chars,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_verification_report(
                verification_results=verification_results,
                top_k=args.top_k,
                snippet_chars=args.snippet_chars,
            )

        failures = collect_verification_failures(verification_results)
        if failures:
            raise SystemExit(
                "verification failed:\n"
                + "\n".join(f"- {failure}" for failure in failures)
            )
        return

    if not args.query:
        raise SystemExit("query is required unless --verify is used")

    results = rank_sections(sections, args.query, args.top_k)
    payload = {
        "query": args.query,
        "top_k": args.top_k,
        "results": [
            result.to_payload(args.query, args.snippet_chars) for result in results
        ],
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print_results(args.query, results, args.snippet_chars)


if __name__ == "__main__":
    main()
