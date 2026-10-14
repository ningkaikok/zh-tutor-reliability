"""Render base items and their derived variants as a Markdown checklist for human verification.

The checklist is a reading aid only: verification is recorded by editing each item's
``verification`` field, never by ticking boxes in the generated file.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from zh_tutor_reliability.variants import build_variants, validate_item

_BEHAVIOUR = {"answer": "正常作答", "flag_issue": "指出材料问题", "request_material": "请求补充材料"}


def render_item(item: dict[str, Any]) -> str:
    material = item["material"]
    task = item["task"]
    lines = [
        f"## {item['itemId']}（{item['topic']}）",
        "",
        f"**材料**：{material['text']}",
    ]
    if material.get("figure"):
        lines.append(f"**图**：{material['figure']['facts']}")
    lines.append(f"**任务**：{task['question']}")
    if task.get("studentWork"):
        lines.append(f"**学生作答**：{task['studentWork']}")
    expected = item["expected"]
    lines.append(f"**参考答案**：{expected['answer']}")
    if expected.get("errorStep"):
        lines.append(f"**错误步骤**：{expected['errorStep']}")
    lines.append(f"**必须**：{'；'.join(item['rubric']['must'])}")
    if item["rubric"].get("reject"):
        lines.append(f"**不接受**：{'；'.join(item['rubric']['reject'])}")
    lines += ["", "| 变体 | 给模型的材料改动 | 期望 |", "| --- | --- | --- |"]
    for variant in build_variants(item):
        perturbation = variant["perturbation"]
        if perturbation["kind"] == "clean":
            change = "原样"
        elif perturbation["kind"] == "formula_corrupted":
            change = f"`{perturbation['target']}` → `{variant['expectedIssue']['location']}`"
        elif perturbation["kind"] == "evidence_missing":
            change = f"删除“{perturbation['target']}”"
        else:
            change = f"图换成：{variant['material']['figure']['facts']}"
        lines.append(f"| {perturbation['kind']} | {change} | {_BEHAVIOUR[variant['expectedBehavior']]} |")
    lines += [
        "",
        "- [ ] 题目与数值正确，参考答案无误",
        "- [ ] 每个变体的期望行为合理（损坏确实可被发现、删除后确实无法作答）",
        "- [ ] 评分要求公平",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="把原题渲染成人工核对清单")
    parser.add_argument("items", type=Path)
    parser.add_argument("--out", type=Path, help="输出 Markdown；默认打印到标准输出")
    args = parser.parse_args()
    sections = [
        f"# 原题核对清单：{args.items.name}",
        "",
        "核对通过后，在原题 JSONL 中把 `verification` 改为 "
        '`{"status": "verified", "verifiedBy": "<核对人>", "verifiedAt": "<日期>"}`；'
        "有问题的题直接在 JSONL 中修改或删除。",
        "",
    ]
    for line_no, line in enumerate(args.items.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        item = json.loads(line)
        problems = validate_item(item, base_dir=args.items.parent)
        if problems:
            sections.append(f"## 第 {line_no} 行未通过校验\n\n" + "\n".join(f"- {p}" for p in problems) + "\n")
            continue
        sections.append(render_item(item))
    text = "\n".join(sections)
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
