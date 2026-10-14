"""Validate reliability base items and derive controlled evidence-defect variants.

Only the base item needs human verification: each perturbation edits one declared
anchor, so the expected behaviour (answer / flag the issue / ask for material) is
known by construction. Variants of the same item share ``itemId`` and must be
analysed as one group, never as independent samples.

Perturbations act on the transcription and figure description only. Image-mode
runs use the clean variant's ``pageImage``; rendering corrupted images is out of
scope until the text-level experiment shows a stable failure mode.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

VARIANT_VERSION = "reliability-variants-v1"
GRADE_BANDS = frozenset({"primary", "middle", "high"})
SOURCE_KINDS = frozenset({"authored", "public", "synthetic"})
TASK_KINDS = frozenset({"explain", "diagnose"})
_ITEM_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_EXPONENT = re.compile(r"\^(\{[^}]*\}|\w)")


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _asset_problems(where: str, asset: Any, base_dir: Path | None) -> list[str]:
    """Assets are optional; when present their bytes must match the pinned hash."""
    if asset is None:
        return []
    if not isinstance(asset, dict) or not _text(asset.get("path")) or not _text(asset.get("sha256")):
        return [f"{where} needs path and sha256"]
    if base_dir is None:
        return []
    path = base_dir / asset["path"]
    if not path.is_file():
        return [f"{where} file is missing"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
        return [f"{where} sha256 does not match"]
    return []


def validate_item(item: Any, *, base_dir: Path | None = None) -> list[str]:
    """Return human-readable problems; an empty list means variants can be derived."""
    if not isinstance(item, dict):
        return ["item is not an object"]
    problems: list[str] = []
    item_id = item.get("itemId")
    if not isinstance(item_id, str) or not _ITEM_ID.match(item_id):
        problems.append("itemId must be a lowercase slug of 3-64 characters")
    if not _text(item.get("topic")):
        problems.append("topic is required")
    if item.get("gradeBand") not in GRADE_BANDS:
        problems.append("gradeBand must be primary, middle or high")
    if item.get("sourceKind") not in SOURCE_KINDS:
        problems.append("sourceKind must be authored, public or synthetic")
    if not _text(item.get("license")):
        problems.append("license is required so results can be published or withheld deliberately")

    verification = item.get("verification")
    if not isinstance(verification, dict) or verification.get("status") not in {"draft", "verified"}:
        problems.append("verification.status must be draft or verified")
    elif verification["status"] == "verified" and not (
        _text(verification.get("verifiedBy")) and _text(verification.get("verifiedAt"))
    ):
        problems.append("verified items need verifiedBy and verifiedAt")

    material = item.get("material")
    raw_text = material.get("text") if isinstance(material, dict) else None
    text = raw_text if isinstance(raw_text, str) and raw_text.strip() else ""
    if not text:
        problems.append("material.text is required")
    if isinstance(material, dict):
        problems += _asset_problems("material.pageImage", material.get("pageImage"), base_dir)
        figure = material.get("figure")
        if figure is not None and not (isinstance(figure, dict) and _text(figure.get("facts"))):
            problems.append("material.figure needs facts")
        if isinstance(figure, dict):
            problems += _asset_problems("material.figure.asset", figure.get("asset"), base_dir)

    task = item.get("task")
    if not isinstance(task, dict) or task.get("kind") not in TASK_KINDS or not _text(task.get("question")):
        problems.append("task needs kind (explain or diagnose) and question")
    elif task["kind"] == "diagnose" and not _text(task.get("studentWork")):
        problems.append("diagnose tasks need studentWork")

    expected = item.get("expected")
    if not isinstance(expected, dict) or not _text(expected.get("answer")):
        problems.append("expected.answer is required")
    elif isinstance(task, dict) and task.get("kind") == "diagnose" and not _text(expected.get("errorStep")):
        problems.append("diagnose tasks need expected.errorStep")

    rubric = item.get("rubric")
    if not isinstance(rubric, dict) or not rubric.get("must") or not all(_text(x) for x in rubric.get("must", [])):
        problems.append("rubric.must needs at least one criterion")

    raw_anchors = item.get("anchors")
    anchors: dict[str, Any] = raw_anchors if isinstance(raw_anchors, dict) else {}
    formulas = anchors.get("formulas") or []
    facts = anchors.get("keyFacts") or []
    if not isinstance(formulas, list) or not isinstance(facts, list):
        return problems + ["anchors.formulas and anchors.keyFacts must be lists"]
    for index, formula in enumerate(formulas):
        if not isinstance(formula, dict) or not _text(formula.get("text")) or not _text(formula.get("witness")):
            # Without a witness a corrupted formula is undetectable, so the item would
            # reward guessing rather than evidence checking.
            problems.append(f"anchors.formulas[{index}] needs text and witness")
        elif text.count(formula["text"]) != 1:
            problems.append(f"anchors.formulas[{index}] must appear exactly once in material.text")
        elif _corrupt_formula(str(item_id), formula["text"]) is None:
            problems.append(f"anchors.formulas[{index}] has no supported corruption")
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict) or not _text(fact.get("text")):
            problems.append(f"anchors.keyFacts[{index}] needs text")
        elif text.count(fact["text"]) != 1:
            problems.append(f"anchors.keyFacts[{index}] must appear exactly once in material.text")

    conflict = item.get("conflictFigure")
    if conflict is not None:
        if not (isinstance(conflict, dict) and _text(conflict.get("facts")) and _text(conflict.get("differs"))):
            problems.append("conflictFigure needs facts and differs")
        elif not (isinstance(material, dict) and isinstance(material.get("figure"), dict)):
            problems.append("conflictFigure requires an original material.figure")
        else:
            problems += _asset_problems("conflictFigure.asset", conflict.get("asset"), base_dir)
    if not formulas and not facts and conflict is None:
        problems.append("at least one formula, key fact or conflictFigure anchor is required")
    return problems


def _corrupt_formula(item_id: str, formula: str) -> tuple[str, str] | None:
    """Pick one deterministic corruption that actually changes the formula."""
    candidates: list[tuple[str, str]] = []
    if "+" in formula or "-" in formula[1:]:
        index = next(i for i, ch in enumerate(formula) if ch == "+" or (ch == "-" and i > 0))
        swapped = "-" if formula[index] == "+" else "+"
        candidates.append(("sign_flip", formula[:index] + swapped + formula[index + 1:]))
    digit = re.search(r"\d", formula)
    if digit:
        changed = str((int(digit.group()) + 1) % 10)
        candidates.append(("digit_change", formula[:digit.start()] + changed + formula[digit.end():]))
    if _EXPONENT.search(formula):
        candidates.append(("exponent_drop", _EXPONENT.sub("", formula, count=1)))
    candidates = [(name, value) for name, value in candidates if value != formula]
    if not candidates:
        return None
    seed = int(hashlib.sha256(f"{item_id}|{formula}".encode()).hexdigest(), 16)
    return candidates[seed % len(candidates)]


def _item_sha256(item: dict[str, Any]) -> str:
    canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_variants(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive the clean variant plus one variant per declared anchor.

    Callers must validate first; this function assumes a valid item.
    """
    material = item["material"]
    figure = material.get("figure")
    common = {
        "itemId": item["itemId"],
        "topic": item["topic"],
        "gradeBand": item["gradeBand"],
        "itemVerified": item["verification"]["status"] == "verified",
        "task": item["task"],
        "reference": item["expected"],
        "rubric": item["rubric"],
        "generator": {"version": VARIANT_VERSION, "itemSha256": _item_sha256(item)},
    }

    def variant(suffix: str, perturbation: dict[str, Any], text: str, figure_value: Any,
                behaviour: str, issue: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "variantId": f"{item['itemId']}--{suffix}",
            **common,
            "perturbation": perturbation,
            "material": {"text": text, "figure": figure_value},
            "inputModes": (
                ["transcription", "image"] if suffix == "clean" and material.get("pageImage") else ["transcription"]
            ),
            "pageImage": material.get("pageImage") if suffix == "clean" else None,
            "expectedBehavior": behaviour,
            "expectedIssue": issue,
        }

    anchors = item.get("anchors") or {}
    variants = [variant("clean", {"kind": "clean", "target": None, "operation": None},
                        material["text"], figure, "answer", None)]
    for index, formula in enumerate(anchors.get("formulas") or []):
        corruption = _corrupt_formula(item["itemId"], formula["text"])
        if corruption is None:
            continue
        operation, corrupted = corruption
        variants.append(variant(
            f"formula-{index}",
            {"kind": "formula_corrupted", "target": formula["text"], "operation": operation},
            material["text"].replace(formula["text"], corrupted, 1), figure,
            "flag_issue",
            {"kind": "formula_corrupted", "location": corrupted, "witness": formula["witness"]},
        ))
    for index, fact in enumerate(anchors.get("keyFacts") or []):
        removed = re.sub(r"[ \t]{2,}", " ", material["text"].replace(fact["text"], "", 1)).strip()
        variants.append(variant(
            f"missing-{index}",
            {"kind": "evidence_missing", "target": fact["text"], "operation": "remove"},
            removed, figure,
            "request_material",
            {"kind": "evidence_missing", "location": fact["text"]},
        ))
    conflict = item.get("conflictFigure")
    if conflict is not None:
        variants.append(variant(
            "figure-conflict",
            {"kind": "figure_conflict", "target": figure["facts"], "operation": "swap_figure"},
            material["text"], {key: conflict[key] for key in ("facts", "asset") if key in conflict},
            "flag_issue",
            {"kind": "figure_conflict", "location": conflict["differs"]},
        ))
    return variants


def derive_file(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read base items and return variants plus a summary; asset paths resolve beside the file."""
    variants: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    seen: set[str] = set()
    items = 0
    verified = 0
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        items += 1
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            problems.append({"line": line_no, "problems": ["invalid JSON"]})
            continue
        found = validate_item(item, base_dir=path.parent)
        if not found and item["itemId"] in seen:
            found = ["duplicate itemId"]
        if found:
            problems.append({"line": line_no, "problems": found})
            continue
        seen.add(item["itemId"])
        verified += item["verification"]["status"] == "verified"
        variants.extend(build_variants(item))
    summary = {
        "items": items,
        "validItems": len(seen),
        "verifiedItems": verified,
        "variants": len(variants),
        "variantsByKind": dict(Counter(v["perturbation"]["kind"] for v in variants)),
        "problems": problems,
    }
    return variants, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="校验可靠性实验原题并生成可控扰动变体，不调用模型")
    parser.add_argument("items", type=Path, help="原题 JSONL")
    parser.add_argument("--out", type=Path, help="可选的新变体 JSONL；拒绝覆盖已有文件")
    args = parser.parse_args()
    try:
        variants, summary = derive_file(args.items)
        if args.out:
            with args.out.open("x", encoding="utf-8") as handle:
                for item in variants:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    except FileExistsError:
        print(json.dumps({"ok": False, "problem": "output_exists_refusing_overwrite"}, ensure_ascii=False))
        return 2
    except (OSError, UnicodeDecodeError):
        print(json.dumps({"ok": False, "problem": "input_or_output_unavailable"}, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
