# Handoff

## 当前结论

- 阶段 C 已结束
- fixed eval 仍是默认回归基线
- 当前仓库已经从 Obsidian 根目录下抽成独立项目
- 回答链路默认只依赖仓库内同级脚本、索引和 eval case
- `build-index` 单测、CLI parity 和安装态 smoke 已切到仓库内 fixture
- 手动重建真实索引仍依赖外部语料，但现在通过显式参数接入
- 统一 CLI 的坏路径报错已收口成纯 CLI 错误，不再直接抛 Python traceback
- 统一 CLI 的 `build-index` 默认写当前工作目录，不写安装目录

## 默认入口

- 文档入口：`README.md`
- 默认回归：`.\run_round.ps1`
- 最小回答：`py -3 .\answer_query.py`
- 统一单测：`py -3 -m unittest discover -p "test_*.py"`
- 索引构建：`py -3 .\build_section_page_index.py --note-root ... --page-index ...`
- CI：`.github/workflows/ci.yml`

## 恢复顺序

1. 先读 `README.md`
2. 跑统一单测：`py -3 -m unittest discover -p "test_*.py"`
3. 跑默认回归：`.\run_round.ps1 "什么是命题" -Json`
4. 如需手动重建真实索引，再显式传外部语料路径执行 `build_section_page_index.py`

## 不要动什么

- 不改 parser
- 不改 retrieval schema
- 不改 fallback 范围
- 不重开阶段 C 的边界拆分
- 不因为迁移工程目录就顺手改检索规则

## 什么时候才值得再动检索

- fixed eval 退化
- 当前最小回答闭环失效
- 出现稳定可复现的新 miss，且不能被现有边界解释

如果只是路径、交接、文档、构建接线问题，优先补工程层，不动检索层。

## 交付层说明

- 当前 baseline 已补最小 CI，验证顺序与本地默认验收一致
- CI 跑在 Windows 上，避免 `powershell` 调用契约和本地脚本环境分叉
- `test_distribution_smoke.py` 已覆盖 editable / `pip install .` / wheel
  三种安装态 smoke
