# discrete-math-rag Onboarding Guide

## What Is This?

这个仓库是一个独立出来的离散数学 RAG backend。你拿到仓库后，不需要还原
Obsidian 工程，也不需要接前端，就能直接做三件事：检索章节、生成最小回答、
跑固定评测。

它服务的对象是维护这个 backend 的开发者，而不是终端用户。项目的核心目标
很克制：把当前检索和回答闭环稳定保存下来，并用固定回归防止工程化改动把
现有行为带偏。边界说明已经写在 [`README.md`](README.md) 和
[`HANDOFF.md`](HANDOFF.md) 里，接手时先默认这些约束是硬的。

---

## Developer Experience

你通常会以两种方式使用这个仓库。第一种是直接从源码根目录运行脚本，
比如 `.\run_round.ps1` 或 `py -3 .\retrieve_sections.py`。第二种是先执行
`python -m pip install -e .`，再通过 `python -m discrete_math_rag` 或
`discrete-math-rag` 走统一 CLI。

统一 CLI 覆盖了五个动作：`answer`、`retrieve`、`eval`、`round`、
`build-index`。如果你要验证工程包装层没有偏离旧入口，直接跑
`python -m unittest test_cli.py`，它会逐项比对新 CLI 和现有脚本的契约。
如果你改的是 `pyproject.toml`、安装链路或 CI，再额外跑
`python -m unittest test_distribution_smoke.py`，它会在临时 venv 里分别验证
editable install、`pip install .` 和 wheel 安装三种形态，再确认统一 CLI 在
非仓库 `cwd` 下可用，且 `build-index` 默认不会把输出写回安装目录。

---

## How Is It Organized?

这个仓库本质上分成三层：核心检索/回答模块、工程编排入口、回归与测试资产。
它没有数据库、网络服务或容器依赖；运行时依赖的核心资源就是仓库里
checked-in 的 `section_page_index.json`，而索引重建时才会碰外部 Obsidian
语料。

```text
Developer
  |
  | CLI / PowerShell
  v
+----------------------+
| Entry Points         |
| `discrete_math_rag/` |
| `*.ps1`              |
+----------+-----------+
           |
           | Python calls
           v
+----------------------+
| Core Modules         |
| `retrieve_sections`  |
| `answer_query`       |
| `build_section_*`    |
+----------+-----------+
           |
           | file I/O
           v
+----------------------+
| Data Assets          |
| `section_page_*.json`|
| external note corpus |
+----------------------+
```

```text
discrete-math-rag/
  discrete_math_rag/        # 统一 CLI 包
  retrieve_sections.py      # 检索与 verify
  answer_query.py           # 最小回答
  build_section_page_index.py
                            # 索引构建入口
  _build_section_page_index_impl.py
                            # 索引构建实现
  run_eval_suite.ps1        # 固定评测入口
  run_round.ps1             # 默认回归入口
  probe_queries.ps1         # probe 编排入口
  test_*.py                 # 契约与回归测试
  section_page_index.json   # checked-in 运行索引
```

| Module | Responsibility |
| --- | --- |
| `discrete_math_rag/cli.py` | 统一 CLI，复用旧模块并对齐旧脚本契约 |
| `retrieve_sections.py` | 检索打分、fixed verify、结果输出 |
| `answer_query.py` | 在 top retrieval 上抽最小回答 |
| `build_section_page_index.py` | 暴露索引重建命令行参数 |
| `_build_section_page_index_impl.py` | 解析外部语料并生成 section-page 记录 |
| `run_eval_suite.ps1` | Windows PowerShell 下的 fixed eval 编排 |
| `run_round.ps1` | 默认回归编排：先 probe，再 eval |

| Dependency | What it is used for | Configured via |
| --- | --- | --- |
| `section_page_index.json` | 默认运行时索引 | 仓库内文件 |
| 外部 Obsidian 语料 | 重建索引时读取笔记与页码索引 | `--note-root`、`--page-index`、`--source-root` |
| Windows PowerShell | 兼容保留的旧入口 | 本地 shell |

这个项目看起来像工具仓，所以架构重点不是服务边界，而是入口边界。你要做
工程化改动时，优先改 `discrete_math_rag/cli.py`、文档和测试，不要先动
`retrieve_sections.py`。

---

## Key Concepts and Abstractions

| Concept | What it means in this codebase |
| --- | --- |
| fixed eval | 一组 checked-in 的 retrieval case，用来锁住现有检索边界 |
| default round | 默认验收流程，等于 probe 加 fixed eval |
| probe | 用一组查询看当前检索结果是否还合理，不是正式评测 |
| checked-in index | 仓库内的 `section_page_index.json`，运行时直接使用 |
| external corpus | 只在 `build-index` 时才需要的 Obsidian 笔记和页码索引 |
| minimal answer loop | `answer_query.py` 基于 top section 生成最短可用回答 |
| retrieval schema | `retrieve_sections.py` 输出的 JSON 结构，不能随便改 |
| PowerShell entrypoints | 现有使用方式，工程化后仍需保持可用 |
| CLI parity test | `test_cli.py`，保证新 CLI 和旧入口行为一致 |
| engineering layer | CLI、文档、打包、测试编排这一层，可以改 |
| retrieval layer | ranking、match、fallback 和 fixed eval 边界，不应顺手改 |

这张表就是你和别人讨论这个仓库时的最小词汇表。如果你发现某个问题只发生在
工程层，不要把它升级成检索层问题。

---

## Primary Flows

最常见的维护流是“改一点工程层，然后确认 baseline 没被带偏”。主流程如下：

```text
You run a command
  |
  v
`discrete_math_rag/cli.py`
  parses subcommand and options
  |
  v
`retrieve_sections.py` or
`answer_query.py`
  runs retrieval / answer logic
  |
  v
`section_page_index.json`
  provides section records
  |
  v
JSON or text output
  for tests, CLI, or PowerShell
```

另外两个常见流：

1. 你跑 `python -m discrete_math_rag eval --json`。`cli.py` 会按固定 suite
   顺序调用 `retrieve_sections.py` 的 verify 逻辑，拼出与
   `run_eval_suite.ps1` 一致的 JSON 契约。
2. 你跑 `python -m discrete_math_rag build-index ...`。构建入口会读取外部
   Obsidian 笔记和页码索引，通过 `_build_section_page_index_impl.py`
   生成新的 `section_page_index.json`。如果省略 `--output`，统一 CLI 会把文件
   写到当前工作目录，而不是安装目录。

如果你想验证包装层没漂移，直接看 `test_cli.py`。它就是“新入口对旧入口”
的回归护栏。

---

## Developer Guide

先把环境起起来：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

日常运行和验证命令：

```powershell
python -m unittest discover -p "test_*.py"
python -m discrete_math_rag round "什么是命题" --json
python -m discrete_math_rag eval --json
python -m unittest test_cli.py
python -m unittest test_distribution_smoke.py
```

最常见的改动路径：

- 加或改工程入口：从 `discrete_math_rag/cli.py` 开始，然后补 `test_cli.py`
- 调整构建接线：从 `build_section_page_index.py` 和
  `_build_section_page_index_impl.py` 开始
- 改文档和交接：从 [`README.md`](README.md) 和
  [`HANDOFF.md`](HANDOFF.md) 开始

| Area | File | Why start here |
| --- | --- | --- |
| CLI 编排 | `discrete_math_rag/cli.py` | 新命令、旧契约兼容、统一入口都在这里 |
| 检索核心 | `retrieve_sections.py` | 所有 retrieve / verify 逻辑都从这里出 |
| 回答核心 | `answer_query.py` | 最小回答闭环只走这一层 |
| 索引构建 | `build_section_page_index.py` | 构建参数面和输出契约在这里 |
| 边界背景 | `HANDOFF.md` | 为什么有些地方不能动，先看这里 |

实操时记住三个提示：

- 先跑单测，再跑 `round`，最后跑 `eval`。这是这个仓库的默认验收顺序。
- 改 CLI 之前先看 `test_cli.py`，它定义了“等价于旧脚本”到底是什么意思。
- 改打包或 CI 之前先看 `test_distribution_smoke.py`，它锁的是“editable /
  非 editable / wheel 三种安装态都还能跑”。
- 如果问题只是路径、打包、命令行或文档，优先在工程层收口，不要顺手去动
  检索策略。
