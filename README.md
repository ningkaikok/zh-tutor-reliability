# zh-tutor-reliability

中文教材辅导的 AI 可靠性实验：教材存在缺页、错公式、图文冲突时，辅导系统能否识别证据问题，
并给出恰当的讲解或请求补充材料。方向、四周试验与去留条件见 [docs/plan.md](docs/plan.md)。

## 快速开始

需要 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
uv run python -m unittest discover -s tests
uv run python -m zh_tutor_reliability.variants data/items/examples.jsonl
```

目录：`data/items/` 人工核对的原题，`data/variants/` 生成的变体，`runs/` 模型原始响应缓存（不入库），
`reports/` 每次实验一页报告。

许可：代码采用 [Apache-2.0](LICENSE)；`data/` 下的原题与变体采用 [CC BY 4.0](data/LICENSE)，使用时请注明出处。
可公开的原题只能是自编或开放许可内容，`license` 字段需与此一致。

## 思路

人工只核对**原题**（正确转写、标准答案、评分规则）。程序从原题按声明的锚点生成损坏版本，
每个变体错在哪里由构造决定，不需要再逐条标注。同一原题的所有变体共享 `itemId`，分析时必须按原题分组，
不能当成相互独立的样本。

## 原题字段（JSONL，每行一题）

| 字段 | 说明 |
| --- | --- |
| `itemId` | 小写短横线标识，3–64 字符 |
| `topic`、`gradeBand` | 主题；`primary` / `middle` / `high` |
| `sourceKind`、`license` | `authored`（自编）/ `public`（开放许可）/ `synthetic`；许可决定结果能否公开 |
| `verification` | `{status: draft \| verified, verifiedBy, verifiedAt}`；`verified` 必须写明核对人和时间 |
| `material.text` | 正确转写的教材片段 |
| `material.figure` | 可选：`{facts, asset?}`，`facts` 是图中事实的文字描述 |
| `material.pageImage` | 可选：`{path, sha256}`，原页图片，用于“直接看图”管线 |
| `task` | `{kind: explain \| diagnose, question, studentWork?}`；诊断题必须有学生作答 |
| `expected` | `{answer, errorStep?, ...}`；诊断题必须有 `errorStep` |
| `rubric` | `{must: [...], reject: [...]}` |
| `anchors.formulas[]` | `{text, witness}`：可被改坏的公式，正文中只能出现一次；`witness` 写明靠什么能发现它被改坏，没有佐证的公式不允许作为锚点 |
| `anchors.keyFacts[]` | `{text}`：解题必需的条件，正文中只能出现一次；删掉后应无法作答 |
| `conflictFigure` | 可选：`{facts, differs, asset?}`，与正文矛盾的替换图及矛盾点 |

`asset` 和 `pageImage` 的路径相对于 JSONL 文件所在目录，并校验 SHA-256。

## 变体

| `perturbation.kind` | 生成方式 | `expectedBehavior` |
| --- | --- | --- |
| `clean` | 原样 | `answer`：应正常作答；此时报告“证据有问题”算误报 |
| `formula_corrupted` | 对锚点公式做一种确定性改动：符号翻转、数字改变或丢失指数 | `flag_issue` |
| `evidence_missing` | 删除一个必需条件 | `request_material`：应说明缺少什么并请求补充，而不是编造 |
| `figure_conflict` | 把图换成 `conflictFigure` | `flag_issue` |

输入方式 `inputModes`：所有变体都可用转写文本；只有提供了 `pageImage` 的 `clean` 变体可额外走看图管线。
看图版本的损坏图片暂不生成，等文本层实验出现稳定的失败模式后再决定是否值得做。

评分时要同时看两边：损坏变体上是否发现问题、定位是否准确；干净变体上能否答对、是否误报。
“全部拒答”在干净变体上会被扣分，不能拿高分。

## 生成变体

```bash
uv run python -m zh_tutor_reliability.variants data/items/<原题>.jsonl --out data/variants/<新变体>.jsonl
```

输出摘要包括题数、已核对题数、各类变体数量和逐行问题。退出码：0 表示全部有效，1 表示有题目未通过校验，
2 表示读写失败或输出文件已存在（不会覆盖）。

`data/items/examples.jsonl` 是两道 `draft` 状态的示例题，只用于演示格式和测试，不计入实验数据。
