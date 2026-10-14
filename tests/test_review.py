"""Acceptance scenarios for the human verification checklist."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from zh_tutor_reliability.review import render_item
from zh_tutor_reliability.variants import build_variants

ITEMS = Path(__file__).resolve().parents[1] / "data" / "items" / "similar-triangles.jsonl"


class ReviewChecklistScenarios(unittest.TestCase):
    def test_user_sees_every_variant_and_its_expectation_before_verifying(self) -> None:
        # Given a drafted item with a formula anchor
        item = next(
            json.loads(line) for line in ITEMS.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["itemId"] == "st-a2-worked-ae"
        )
        # When the checklist is rendered
        text = render_item(item)
        # Then the reviewer sees the answer, one row per variant and what the model should do
        self.assertIn("**参考答案**：EC=9", text)
        self.assertEqual(text.count("| formula_corrupted |"), 2)
        self.assertIn("指出材料问题", text)
        self.assertEqual(text.count("\n| "), len(build_variants(item)) + 2)

    def test_user_can_review_every_drafted_similar_triangle_item(self) -> None:
        # Given the drafted topic file, Then every item renders and none is marked verified yet
        for line in ITEMS.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            self.assertIn(item["itemId"], render_item(item))
            self.assertEqual(item["verification"]["status"], "draft")


if __name__ == "__main__":
    unittest.main()
