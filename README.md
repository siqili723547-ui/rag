# 离散数学 RAG

这是从 `Obsidian Vault/math/离散数学及其应用/rag/backend` 抽出的独立仓库，目标不是重做检索，而是把现有 backend 收口成一个别人拿到就能安装、运行、验证和维护的工程化项目。

当前边界保持不变：

- 不改 parser
- 不改 retrieval schema
- 不改 fallback 范围
- 不重开检索策略和 fixed eval 边界
- 不为了工程化顺手改 ranking / match 逻辑
- 所有改动都必须继续通过单测、默认回归和 fixed eval

## 你会得到什么

- 一个 checked-in 的 `section_page_index.json`，克隆后就能直接做检索和回答
- 一套统一 CLI：`answer`、`retrieve`、`eval`、`round`、`build-index`
- 一套保留兼容的 PowerShell 入口，不破坏当前使用方式
- 一套可执行的回归基线：单测 -> 默认回归 -> fixed eval
- 一套基于仓库内 fixture 的 `build-index` 测试，不需要外部 Obsidian Vault
- 一份接手文档：`ONBOARDING.md`

## 环境要求

- Windows PowerShell
- Python 3.10+
- 可选：外部 Obsidian 语料，仅在你需要重建 `section_page_index.json` 时才需要

## 10 分钟首次运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python .\run_validation.py quick
python .\run_validation.py round
python .\run_validation.py eval
```

如果你不想先装成 editable package，也可以直接用仓库内脚本：

```powershell
py -3 .\run_validation.py quick
py -3 .\run_validation.py round
py -3 .\run_validation.py eval
```

## 统一 CLI

安装后可以用两种方式：

- `python -m discrete_math_rag ...`
- `discrete-math-rag ...`

推荐从 `python -m discrete_math_rag --help` 开始。当前子命令与旧入口的对应关系如下：

| 动作 | 新 CLI | 旧入口 |
| --- | --- | --- |
| 回答 | `python -m discrete_math_rag answer "什么是命题" --json` | `py -3 .\answer_query.py "什么是命题" --json` |
| 检索 | `python -m discrete_math_rag retrieve "什么是函数" --json` | `py -3 .\retrieve_sections.py "什么是函数" --json` |
| 固定评测 | `python -m discrete_math_rag eval --json` | `.\run_eval_suite.ps1 -Json` |
| 默认回归 | `python -m discrete_math_rag round "什么是命题" --json` | `.\run_round.ps1 "什么是命题" -Json` |
| 重建索引 | `python -m discrete_math_rag build-index ...` | `py -3 .\build_section_page_index.py ...` |

PowerShell 入口会继续保留，当前 CI 也仍然用它们做回归。
另外，`test_distribution_smoke.py` 现在会补三种安装形态的 CLI smoke：

- 仓库源码 `python -m pip install -e .`
- 非 editable 安装 `python -m pip install .`
- wheel 安装

这些 smoke 都会在非仓库 `cwd` 下同时验证 `python -m discrete_math_rag`
和 `discrete-math-rag`，并确认安装态 `build-index` 默认不会把输出写回
venv / site-packages 一侧。
本地如果想按职责分层跑验证，直接用 `python .\run_validation.py quick`、
`python .\run_validation.py install-smoke` 和 `python .\run_validation.py full`。

## 推荐工作流

### 1. 日常改动前先跑快单测

```powershell
python .\run_validation.py quick
```

### 2. 改了入口、编排或文档后跑默认回归

```powershell
python .\run_validation.py round
```

### 3. 改了任何可能碰到检索边界的代码后跑 fixed eval

```powershell
python .\run_validation.py eval
```

### 4. 改了 CLI 或脚本契约后跑 CLI 等价性测试

```powershell
python -m unittest test_cli.py
```

### 5. 改了打包、安装方式或 CI 后跑安装态 smoke

```powershell
python .\run_validation.py install-smoke
```

## `build-index` 测试 vs 真实索引重建

日常单测和 `build-index` 相关测试现在都基于仓库内 fixture，可直接复现：

- `test_build_section_page_index.py`
- `test_cli.py` 里的 `build-index` CLI parity
- `test_distribution_smoke.py` 里的安装态 `build-index` smoke

这些测试统一复用 `test_fixtures/build_index/`，不需要外部 Obsidian Vault。

只有在你要手动重建或覆盖仓库里的真实 `section_page_index.json` 时，才需要提供外部 Obsidian 语料。

## 重建 `section_page_index.json`

运行时默认使用仓库里 checked-in 的 `section_page_index.json`。只有在你要从外部语料重新生成索引时，才需要提供 Obsidian 路径。

统一 CLI 的 `build-index` 如果省略 `--output`，会默认写到当前工作目录下的
`.\section_page_index.json`。这让 editable / 非 editable / wheel 安装态都不会
意外改写安装目录里的运行时资产；如果你就是要覆盖仓库里的 checked-in 索引，
请显式传 `--output .\section_page_index.json` 并在仓库根目录执行。

```powershell
$vaultRoot = "C:\path\to\Obsidian Vault"

python -m discrete_math_rag build-index `
  --output .\section_page_index.json `
  --note-root "$vaultRoot\math\离散数学及其应用\笔记" `
  --page-index "$vaultRoot\math\离散数学及其应用\页码索引.md" `
  --source-root $vaultRoot `
  --verify
```

参数说明：

- `--note-root`：笔记语料根目录
- `--page-index`：页码索引文件
- `--source-root`：可选，用来把 `source_path` 保持成相对路径
- `--verify`：打印默认抽查 section 的映射结果

如果你希望和当前 checked-in 索引保持同样的 `source_path` 契约，`--source-root` 应指向原来的 vault 根目录。

## 本地验证顺序

推荐把下面三步当成默认验收顺序：

```powershell
python .\run_validation.py quick
python .\run_validation.py round
python .\run_validation.py eval
```

如果你需要验证“新 CLI 没有偏离旧脚本契约”，再补一条：

```powershell
python -m unittest test_cli.py
```

如果你需要验证“editable / 非 editable / wheel 安装后还能直接跑统一 CLI”，再补一条：

```powershell
python .\run_validation.py install-smoke
```

## 常见排查

### `python -m discrete_math_rag` 找不到模块

- 先确认你在仓库根目录
- 先执行 `python -m pip install -e .`
- 再跑 `python -m discrete_math_rag --help`

### PowerShell 脚本找不到 Python

- 显式传 `-Python python`
- 或继续用 `py -3` 直接跑对应 `.py` 入口

示例：

```powershell
.\run_round.ps1 "什么是命题" -Python python -Json
```

### `build-index` 找不到外部语料

- 如果你只是跑 `test_build_section_page_index.py`、`test_cli.py` 或 `test_distribution_smoke.py`，先不要找 Obsidian Vault；这些测试已经走仓库内 fixture
- 先确认 `--note-root` 和 `--page-index` 路径都存在
- 只有你在手动重建真实索引时，才需要额外提供 `--source-root`

### 默认回归过了，但 fixed eval 失败

先不要改检索逻辑。优先检查：

- 是否误动了 JSON 契约、路径或 CLI 参数传递
- 是否改坏了 eval case 文件选择或 `top_k`
- 是否只是工程包装层输出变了，但底层 `retrieve_sections.py` 没变

这类问题优先在工程层修，不在检索层修。

## 仓库结构

- `discrete_math_rag/cli.py`：统一 CLI 和工程编排层
- `retrieve_sections.py`：检索与 verify 主入口
- `answer_query.py`：最小回答闭环
- `build_section_page_index.py`：索引构建入口
- `_build_section_page_index_impl.py`：索引构建实现
- `run_validation.py`：分层验证入口（quick / install-smoke / full）
- `run_eval_suite.ps1`：固定评测 PowerShell 入口
- `run_round.ps1`：默认回归 PowerShell 入口
- `probe_queries.ps1`：并行 probe 的 PowerShell 入口
- `test_*.py`：默认契约测试与 CLI 等价性测试
- `HANDOFF.md`：边界与阶段结论
- `ONBOARDING.md`：新接手同学的上手文档

## CI

仓库包含最小 CI：`.github/workflows/ci.yml`。

- 运行环境：`windows-latest`
- 验证顺序：快单测 -> install-mode smoke -> extra wheel CLI smoke -> 默认回归 -> fixed eval
- 目标：把当前“本地可跑”的 baseline 固化成“push / PR 可验证”的 baseline

## 相关文档

- 接手先读：[`ONBOARDING.md`](ONBOARDING.md)
- 边界和移交背景：[`HANDOFF.md`](HANDOFF.md)
