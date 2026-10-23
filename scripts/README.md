# Scripts 工具说明

本目录包含 `start.ipynb` 使用的流程函数，以及可单独运行的核对和维护工具。大多数脚本只依赖 Python 标准库；`mineru_pdf_parser.py` 额外需要 `requests`。CSD 查询和 CIF 导出需要本机已安装、已授权的 CSD Python API（`ccdc`），不能通过 pip 安装。PDF 下载另需 Node.js、Chrome 和 `skills/html-page-saver/`；模型提取由 Notebook 调用 Codex CLI 与 `skills/rare-earth-literature-extractor/` 完成。

从项目根目录运行下列命令。Notebook 工作流默认预览或关闭写入开关；单独运行的工具则按各条说明处理文件。运行批量工具前请先备份重要数据。

## 主流程工具

| 文件 | 用途与入口 | 主要输入/输出及注意事项 |
|---|---|---|
| `ccdc_data.py` | 共享函数库，不单独运行。 | 读取 `.gcd`、查询本地 CSD SQLite 数据库、规范 DOI、解析并筛选分子式。CSD 数据目录可用 `CSD_DATA_DIR` 或 `CSD_HOME` 配置。 |
| `filter_gcd.py` | 第 1 步；由 Notebook 调用 `run(...)`。 | 输入 `.gcd`，查询 CSD 分子式后写筛选 `.gcd` 与逐 refcode 报告 CSV。运行函数会写文件。 |
| `export_metadata.py` | 第 2 步；由 Notebook 调用 `run(...)`。 | 从筛选后的 `.gcd` 查询 CSD，写出含 `refcode, doi, formula, ccdc_number` 的 CSV。需要本机 CSD 数据库。 |
| `export_cifs.py` | 第 3 步；Notebook 调用 `preview(...)` 或 `run(...)`；作为命令行时仅支持内部 worker 参数。 | `preview` 只检查 CCDC 编号、目标文件和覆盖状态，不访问 CSD、不写文件；`run` 会启动隔离的 CSD 子进程、导出 CIF 并写日志。需要 CSD Python 与有效 CCDC License。`CSD_API_HOME`、`CSD_PYTHON` 可配置 API 和解释器位置。 |
| `download_batches.py` | 第 4 步；由 Notebook 调用 `run(...)`。 | 从 DOI CSV 按批次调用 `html-page-saver` 下载 PDF，并更新下载日志和失败 DOI 清单。需要 Node.js、Chrome、skill 脚本；可能触发浏览器交互和网络访问。 |
| `mineru_pdf_parser.py` | 第 5 步；可由 Notebook 调用，也可直接运行。 | 将本地 PDF 交给 MinerU API，输出 DOI 同名 Markdown 和转换日志。需要 `requests`、`MINERU_API_KEY`（或本地 `.env`）及网络；默认跳过已有 Markdown，`--overwrite` 才覆盖。命令示例：`python scripts/mineru_pdf_parser.py --limit 5`。 |
| `extract_cif_structures.py` | CIF 结构卡处理；由 Notebook 调用 `run(...)`，也可直接运行。 | 本地解析 `CIFs/` 并生成 `data/cif_structure_cards/` JSON。默认处理并写入；`--limit N` 限量，`--overwrite` 才覆盖已有卡片。Notebook 预览使用 `preview=True`。 |

## 审核与数据维护

| 文件 | 用途与入口 | 写入行为/风险 |
|---|---|---|
| `audit_card_ccdc.py` | `python scripts/audit_card_ccdc.py --preview` | Compare paper-card CCDC numbers/refcodes against the DOI-linked `data/structures.csv`. Preview is read-only; without `--preview` writes `data/process_csv/card_ccdc_audit.csv`. Unnumbered compounds may be legitimate; review against the paper/SI/CIF before editing any card. |
| `audit_integrity.py` | `python scripts/audit_integrity.py` | 对齐 PDF、SI、Markdown、文献卡和 CIF，重建 `data/final_integrity_ledger.csv`、`data/final_integrity_issues.csv`、`data/final_synthesis_gaps.csv`，并更新 `data/card_review.md` 中的当前审核章节；CIF 补导出名单写入 `data/process_csv/final_missing_cif_targets.csv`。会覆盖这些生成结果，不修改源文件。 |
| `backfill_card_ccdc.py` | `python scripts/backfill_card_ccdc.py` | 默认只生成 `data/card_ccdc_match_review.csv` 报告；只有明确加入 `--apply` 才会备份并修改论文 card 中可唯一匹配的 CCDC 编号。应用前先审阅报告。 |
| `build_high_quality_samples.py` | `python scripts/build_high_quality_samples.py` | 从现有卡片构建 `data/high_quality_samples/` 子集并写 provenance ledger/README；复制目标文件可能被更新。源卡不移动。 |
| `select_large_cluster_pdfs.py` | `python scripts/select_large_cluster_pdfs.py` | 从已有卡片中选出核数大于 20 且有本地 PDF 的文章，写入 `data/process_csv/large_cluster_papers_gt20.csv`；保留仍匹配条目的重提取状态。 |
| `select_reextract_folder.py` | 由 Notebook 导入的辅助函数库，不建议直接执行。 | 按文件夹中的 DOI 文件选择提取队列；`write_queue` 和 `record_result` 会写队列 CSV，单纯调用 `select_rows`/`merge_status` 不写入。 |
| `check_markdown_quality.py` | `python scripts/check_markdown_quality.py` | 检查 PDF 对应 Markdown 是否缺失、过短或以图片为主，写 `data/md_quality_issues.csv`。默认还会复制可疑 PDF/Markdown 到隔离目录；用 `--no-copy` 只生成报告。 |
| `align_document_names.py` | `python scripts/align_document_names.py` | 按 metadata DOI 重命名 PDF、Markdown、SI、提取卡及日志相关文件，并写对齐报告；**没有预览模式**，运行前应先备份相关目录。 |
| `rebuild_si_card_review.py` | `python scripts/rebuild_si_card_review.py` | 从 `data/process_csv/si_required.csv` 和本地材料重建 `data/card_review.md`。这是脚本而非导入库：模块加载时就会读取输入并写报告，不要从 Notebook 导入。 |

## 辅助工具

| 文件 | 用途与入口 | 输出与限制 |
|---|---|---|
| `slice_structure_figures.py` | `python scripts/slice_structure_figures.py --input documents/md --output data/structure_figure_slices` | 从 Markdown 提取图注及附近结构讨论段落，输出 JSON。是基于关键词和段落距离的启发式切片，不做语义核验；会创建目录并写/覆盖同名 JSON。 |
| `__init__.py` | Python 包标记。 | 无独立操作。 |

## 环境与启动

安装本项目 Python 包依赖前，先确认当前终端中的 `python` 确实是配置好的 CSD Python；不要新建普通 `.venv`：

```powershell
python -c "import sys; print(sys.executable)"
python -m pip install -r requirements.txt
```

当前 `requirements.txt` 只列出脚本实际使用的 pip 包 `requests`。`ccdc` 必须来自本机 CSD 安装和许可证，不能用 pip 替代。`activate_csd.ps1` 依赖 `$CSD_API_HOME\miniconda\Scripts\Activate.ps1`；如果该文件在本机不存在，应先修复或配置激活路径，再从同一已激活终端启动 Jupyter。Notebook 的项目根目录、开关、默认输入和输出路径说明见根目录 `README.md` 与 `start.ipynb`。

## SI recovery and end-of-run checks

In `start.ipynb` section 7, SI completion reads the existing article card, SI files, prior extraction diagnostics, and `si_required.csv`; it asks for a synthesis-only patch. It does not read the main article or replace the entire card. Section 7.1 can instead use `RETRY_FULL_CARD=True` to make a new card, with optional main article (`RETRY_INCLUDE_MAIN=True`) and per-DOI `.md`/`.txt` review notes from `RETRY_HINTS_DIR`. The old card is backed up under `data/extraction_logs/` before validated replacement. `RETRY_ONLY_THESE` can include a manually reviewed DOI absent from `si_required.csv`, provided the card and SI Markdown exist. Both modes call the model only after the execute switch is enabled.

After article cards, run the notebook's 6.3 CCDC reconciliation. Before CIF card extraction, section 8.1 builds the >20-metal-nucleus paper list. Section 10 runs `audit_integrity.py --metadata data/structures.csv` and regenerates `data/final_integrity_ledger.csv`, issues, synthesis gaps and missing-CIF targets. The skill-local `rare_earth_cluster_skill/cluster_ledger.csv` is a different corpus index. None of these CSV checks proves a chemical identity or fixes cards automatically.

人工审阅结果保存在 `data/`，程序索引、状态、队列、补导出目标保存在 `data/process_csv/`。`data/process_csv/project_card_ledger.csv` 是可重建搜索索引；`data/card_review.md` 中的自动审核段逐 card/化合物描述具体缺项。`rebuild_si_card_review.py` 重建历史 SI 审核快照，会保留已有自动完整性审计段；运行前备份自己手工修改的报告。
