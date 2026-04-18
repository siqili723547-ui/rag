from __future__ import annotations

import unittest
from pathlib import Path

from retrieve_sections import load_sections

from answer_query import build_answer_payload


BACKEND_DIR = Path(__file__).resolve().parent
INDEX_PATH = BACKEND_DIR / "section_page_index.json"


class AnswerQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sections = load_sections(INDEX_PATH)

    def test_definition_query_returns_concise_answer_with_source_and_pdf(self) -> None:
        payload = build_answer_payload(self.sections, "什么是命题", top_k=3)

        self.assertEqual(payload["query"], "什么是命题")
        self.assertEqual(payload["section_id"], "3.2.1")
        self.assertIn("具有确切真值的陈述句", payload["answer"])
        self.assertIn("命题", payload["answer"])
        self.assertEqual(
            payload["source_path"],
            "math/离散数学及其应用/笔记/第3章 命题逻辑/3.2 命题与命题联结词/3.2.1 命题.md",
        )
        self.assertEqual(payload["pdf_page_start"], 67)
        self.assertEqual(payload["pdf_page_end"], 67)

    def test_concept_overview_query_falls_back_to_abstract_summary(self) -> None:
        payload = build_answer_payload(self.sections, "什么是量词", top_k=3)

        self.assertEqual(payload["section_id"], "4.2.2")
        self.assertIn("量词是谓词逻辑中用于表达个体词数量特征的重要工具", payload["answer"])
        self.assertEqual(payload["pdf_page_start"], 127)
        self.assertEqual(payload["pdf_page_end"], 129)


if __name__ == "__main__":
    unittest.main()
