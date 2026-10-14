"""Acceptance scenarios for reliability base items and controlled evidence-defect variants."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from zh_tutor_reliability.variants import build_variants, derive_file, validate_item

EXAMPLES = Path(__file__).resolve().parents[1] / "data" / "items" / "examples.jsonl"


def _item() -> dict:
    return {
        "itemId": "ratio-case",
        "topic": "平行线分线段成比例",
        "gradeBand": "middle",
        "sourceKind": "authored",
        "license": "CC0-1.0",
        "verification": {"status": "verified", "verifiedBy": "author", "verifiedAt": "2026-10-14"},
        "material": {
            "text": "DE∥BC，AD=2，DB=3，AE=4。由比例得 2/3=4/EC，所以 EC=6。",
            "figure": {"facts": "DE 与 BC 平行"},
        },
        "task": {"kind": "explain", "question": "求 EC。"},
        "expected": {"answer": "EC=6"},
        "rubric": {"must": ["使用 AD/DB=AE/EC"]},
        "anchors": {
            "formulas": [{"text": "2/3=4/EC", "witness": "AD=2、DB=3、AE=4"}],
            "keyFacts": [{"text": "AE=4。"}],
        },
        "conflictFigure": {"facts": "DE 与 BC 相交", "differs": "图中 DE 与 BC 不平行"},
    }


class ReliabilityVariantScenarios(unittest.TestCase):
    def test_user_derives_one_variant_per_anchor_with_known_expected_behaviour(self) -> None:
        # Given a verified base item with a formula, a key fact and a conflicting figure
        item = _item()
        # When variants are derived
        variants = {v["perturbation"]["kind"]: v for v in build_variants(item)}
        # Then each defect is applied once and the expected behaviour follows from construction
        self.assertEqual(set(variants), {"clean", "formula_corrupted", "evidence_missing", "figure_conflict"})
        self.assertEqual(variants["clean"]["expectedBehavior"], "answer")
        self.assertEqual(variants["clean"]["material"]["text"], item["material"]["text"])
        corrupted = variants["formula_corrupted"]
        self.assertNotIn("2/3=4/EC", corrupted["material"]["text"])
        self.assertIn(corrupted["expectedIssue"]["location"], corrupted["material"]["text"])
        self.assertEqual(corrupted["expectedBehavior"], "flag_issue")
        self.assertNotIn("AE=4。", variants["evidence_missing"]["material"]["text"])
        self.assertEqual(variants["evidence_missing"]["expectedBehavior"], "request_material")
        self.assertEqual(variants["figure_conflict"]["material"]["figure"]["facts"], "DE 与 BC 相交")
        # And all variants stay grouped under the same item for analysis
        self.assertEqual({v["itemId"] for v in variants.values()}, {"ratio-case"})
        self.assertTrue(all(v["itemVerified"] for v in variants.values()))

    def test_user_regenerates_variants_and_gets_identical_output(self) -> None:
        # Given the same item derived twice, Then variants are byte-identical so reruns are comparable
        self.assertEqual(build_variants(_item()), build_variants(copy.deepcopy(_item())))

    def test_user_cannot_add_undetectable_or_ambiguous_anchors(self) -> None:
        # Given anchors that would reward guessing or edit the wrong span
        no_witness = _item()
        no_witness["anchors"]["formulas"][0].pop("witness")
        repeated = _item()
        repeated["anchors"]["keyFacts"] = [{"text": "EC"}]
        nothing = _item()
        nothing["anchors"] = {}
        nothing.pop("conflictFigure")
        # When validated, Then each is rejected with a reason
        self.assertIn("anchors.formulas[0] needs text and witness", validate_item(no_witness))
        self.assertIn("anchors.keyFacts[0] must appear exactly once in material.text", validate_item(repeated))
        self.assertIn("at least one formula, key fact or conflictFigure anchor is required", validate_item(nothing))

    def test_user_marks_item_verified_only_with_reviewer_record(self) -> None:
        # Given a verified item without reviewer and a draft item
        unverified = _item()
        unverified["verification"] = {"status": "verified"}
        draft = _item()
        draft["verification"] = {"status": "draft"}
        # Then the first is rejected and the second derives variants flagged as unverified
        self.assertIn("verified items need verifiedBy and verifiedAt", validate_item(unverified))
        self.assertEqual(validate_item(draft), [])
        self.assertFalse(any(v["itemVerified"] for v in build_variants(draft)))

    def test_user_runs_checked_in_examples_without_problems(self) -> None:
        # Given the schema examples in the repository, When derived from file, Then all items are valid
        variants, summary = derive_file(EXAMPLES)
        self.assertEqual(summary["problems"], [])
        self.assertEqual(summary["verifiedItems"], 0)
        self.assertEqual(summary["variants"], len(variants))

    def test_user_sees_line_level_problems_and_duplicate_items(self) -> None:
        # Given a file with a valid item, its duplicate and a broken line
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "items.jsonl"
            line = json.dumps(_item(), ensure_ascii=False)
            path.write_text(f"{line}\n{line}\nnot json\n", encoding="utf-8")
            # When derived
            variants, summary = derive_file(path)
        # Then only the first item produces variants and the rest are reported by line
        self.assertEqual(summary["validItems"], 1)
        self.assertEqual([p["line"] for p in summary["problems"]], [2, 3])
        self.assertEqual(len(variants), 4)


if __name__ == "__main__":
    unittest.main()
