# Cluster Agent：CCDC 文献与结构导出

本项目保留一条从 CCDC 数据到文献结构卡片的工作流：
0. 先用conquest从CCDC中初步筛选结构，并导出refcode list（`.gcd`）。(不在此项目文件夹内进行)
1. 从 CCDC 导出的 refcode list（`.gcd`）中进一步筛选 refcode。
2. 从筛选后的 `.gcd` 导出 `refcode / doi / formula / ccdc_number` CSV。
3. 根据 CSV 导出 CIF，并统一命名为 `{ccdc_number}.cif`。
4. 根据 CSV 中的 DOI 分批调用本地 `html-page-saver` skill 下载 PDF，同时累计保存下载失败的 DOI，供人工下载。
5. 使用 MinerU 将 PDF（原文\综述文献\SI） 转为 DOI 同名的 Markdown，只保留主 Markdown，临时 ZIP 和图片不落盘。（需要自己创建.env文件记录MinerU API Key）
6. 使用 `rare-earth-literature-extractor` skill 和 Codex CLI 从 Markdown（PDF 兜底）提取稀土 cluster/complex 合成卡片，并记录需要 SI 补充合成信息的 DOI。
7. 使用 `rare-earth-literature-extractor` skill 和 Codex CLI 从 Markdown 格式的SI信息提取合成卡片。
8. 使用 `review-knowledge-extractor` skill 和 Codex CLI 从 Markdown 格式的综述文献中提取综述知识卡片 
9. 使用 `scripts.extract_cif_structures.py` 脚本从 CIF 中提取结构卡片。

`start.ipynb` 是按需执行的操作面板，不要使用 Run All。筛选、metadata 导出、PDF 质量检查、CIF 导出、下载、MinerU、模型提取和 CIF 结构卡写入默认都只预览或关闭；核对输入与输出后，再打开对应单元的 `*_EXECUTE` 开关。Notebook 会从当前目录祖先自动发现项目根目录，也可通过 `CLUSTER_AGENT_ROOT` 指定。项目内路径集中在初始化单元中按 `ROOT` 组成，输入 GCD 与筛选条件也可在对应单元修改。

## 一、运行环境

- CSD Python：由 `CSD_PYTHON` 或 `CSD_API_HOME` 配置
- CCDC/CSD 数据库：`D:\CCDC\ccdc-data\csd\*.sqlite`
- Node.js
- Chrome
- 本地下载 skill：`skills/html-page-saver/`

先用miniconda创建CSD环境：
本机路径可通过环境变量覆盖：`CSD_API_HOME` 指向 CSD Python API 安装目录，`CSD_PYTHON` 指向 CIF 导出用的 Python，`CSD_HOME` 或 `CSD_DATA_DIR` 指向 CSD 数据目录，`NODE_EXE` 和 `CODEX_JS` 用于指定 Node.js 与 Codex CLI。未设置时保留当前 Windows 安装路径作为默认值。启动脚本从自身目录进入项目，不要求项目固定放在特定目录。

建议先运行：

```powershell
.\activate_csd.ps1
```

在 Notebook 编辑器中明确选择 `cluster-agent-csd` kernel。若从终端启动 Jupyter，先在已激活 CSD 的同一终端启动，再从该终端运行 Jupyter，使 kernel 继承 CSD 环境。CIF 导出必须使用 CSD 自带 Python，并且本机 CCDC License 必须已经激活。

不要重新建立普通项目 `.venv`；本项目的 CIF 导出依赖 CSD 自带环境。

## 二、标准工作流程

### 第 1 步：筛选 `.gcd`

输入：

```text
inputs/complex_cluster.gcd
```

Notebook 调用：

```python
from scripts.filter_gcd import run as filter_gcd

filter_gcd(
    gcd_path=ROOT / "inputs" / "complex_cluster.gcd",
    out_gcd=ROOT / "data" / "filtered.gcd",
    report_csv=ROOT / "data" / "filter_report.csv",
    must_contain=[],
    forbid=[],
    element=[],
    metals="",
    ignore_solvents=False,
    exclude_formula_n=False,
)
```

主要筛选参数：

- `must_contain=["Gd"]`：必须含指定元素。
- `forbid=["W"]`：排除含指定元素的结构。
- `element=["O>=10", "Gd=4"]`：按元素数量筛选。
- `metals=">=4"` 或 `metals="4-12"`：按金属原子总数筛选。
- `ignore_solvents=True`：统计元素时忽略常见溶剂组分。
- `exclude_formula_n=True`：排除化学式中带小写聚合变量 `n` 的记录。
- `contains="Gd"`：化学式必须含指定文本。
- `regex=r"..."`：使用正则表达式筛选化学式。

输出：

```text
data/filtered.gcd
data/filter_report.csv
```

`filter_report.csv` 会记录每个 refcode 是否保留及被排除的原因。

Notebook 默认没有化学式筛选条件，相当于先对 refcode 规范读取和去重。确认条件后再填写筛选参数。

### 第 2 步：导出结构与 DOI CSV

输入：

```text
data/filtered.gcd
```

输出：

```text
data/structures.csv
```

列顺序固定为：

```text
refcode,doi,formula,ccdc_number
```

同一篇文献可能对应多个 refcode，因此 CSV 行数通常大于唯一 DOI 数。下载前会对 DOI 去重并保持首次出现的顺序。

### 第 3 步：导出 CIF

输入：

```text
data/structures.csv
```

输出：

```text
CIFs/{ccdc_number}.cif
data/process_csv/export_cifs_log.csv
```

规则：

- CCDC 编号查询按编号去重，输出 `{ccdc_number}.cif` 到 `CIFs` 目录；同号多 refcode 时保留来源中第一个 refcode。
- 精确 refcode 查询按 refcode 去重；若多个 refcode 解析到同一 CCDC 号，分别输出 `{ccdc_number}_{refcode}.cif`。
- `overwrite=False` 时跳过已经存在且非空的 CIF。
- Notebook Cell 7 默认只读预览目标去重、编号校验和本地已有 CIF；预览不访问 CSD、不创建目录、不写日志。
- `CIF_EXPORT_EXECUTE=True` 后才启动 CSD 子进程，导出状态写入 `data/process_csv/export_cifs_log.csv`。

### 第 4 步：分批下载 PDF

输入：

```text
data/structures.csv
```

输出：

```text
documents/pdf/{规范化DOI}.pdf
documents/download_log.csv
documents/failed_dois.csv
```

示例：

```python
from scripts.download_batches import run as download_batch

download_batch(
    csv_path=ROOT / "data" / "structures.csv",
    pdf_dir=ROOT / "documents" / "pdf",
    batch_size=50,
    batch_index=0,
    failed_csv=ROOT / "documents" / "failed_dois.csv",
    log_csv=ROOT / "documents" / "download_log.csv",
    challenge_timeout=120,
    headed=True,
)
```

`batch_index` 从 **0** 开始。若 `batch_size=50`：

- `batch_index=0`：第 1–50 个唯一 DOI。
- `batch_index=1`：第 51–100 个唯一 DOI。
- `batch_index=2`：第 101–150 个唯一 DOI。
如果要修改 `batch_size`，最好从 `batch_index=0` 开始，否则可能会跳过未下载的 PDF。

下载下载规则：

- DOI 自动规范化、去重，并保持 CSV 中的原始顺序。
- PDF 文件名中的 `/` 等字符会转换成下划线。
- 已存在且文件头为 `%PDF-` 的文件会跳过。
- 优先尝试常见出版社 PDF 直链。
- 直链失败后，打开 DOI 落地页并提取 `citation_pdf_url`。
- 下载失败的 DOI 累计写入 `documents/failed_dois.csv`。
- 重跑同一 DOI 并成功后，会自动从失败清单中移除。
- 兼容旧版宽表 `documents/download_log.csv`，不会主动删除旧列和历史记录。

## 第 6 步：使用 Codex CLI 提取结构基础卡片

新提取流程位于：

```text
skills/rare-earth-literature-extractor/
```

它让 Codex 模型读取整篇本地 PDF，先解析 compound 1/2、同系物和代指关系，再生成严格 JSON 卡片（主要保存基础信息和合成信息）。

按主文 Markdown 建立 DOI 级任务队列；`documents/md/*_si.md` 不会被当成独立论文，而会作为对应文章的 SI 来源附加到队列行：

```powershell
python skills/rare-earth-literature-extractor/scripts/build_queue.py
```

在 `start.ipynb` 中预览队列不会写入文件；命令行也可加 `--preview` 只在内存中构建。

默认优先读取 `data/structures.csv`；如果该文件尚未生成，则使用保留的 `data/cluster_complex.csv`。输出：

```text
data/process_csv/extraction_queue.csv
```

先小批量运行：

```powershell
python skills/rare-earth-literature-extractor/scripts/run_codex_batch.py --limit 5
```

每篇文献的结果保存到：

```text
data/extracted_cards/{规范化DOI}.json
```

如果正文没有包含明确试剂名称和数值用量的合成方案，验证脚本会将该文献 DOI 写入（即需要人工下载 SI补全信息）：

```text
data/process_csv/si_required.csv
```

性质字段按以下顺序保存：

1. 是否报告磁学或光学性质；
2. 性质类型为 `magnetic`、`optical`、`both` 或 `none`；
3. 再保存具体测量值、单位、条件和磁学/光学应用。

催化、电化学、吸附、生物活性等其他性质不会进入结构卡片。开始大批量处理前，应检查前 5–10 篇结果和 `data/process_csv/si_required.csv`，确认提取规则符合预期。
## 三、项目核心目录

```text
Cluster_agent/
├─ inputs/                     # 原始 .gcd 输入
├─ data/                       # 筛选结果、结构 CSV 和运行日志
├─ CIFs/                       # 按 CCDC 号命名的 CIF
├─ Cards/                      # 从 Codex CLI 提取的结构基础卡片
├─ documents/
│  ├─ pdf/                     # 已下载 PDF，重要数据
│  ├─ failed_dois.csv          # 人工下载清单
│  └─ download_log.csv         # 下载账本
├─ scripts/
│  ├─ ccdc_data.py             # GCD、SQLite、DOI、分子式公共函数
│  ├─ filter_gcd.py            # 第 1 步
│  ├─ export_metadata.py       # 第 2 步
│  ├─ export_cifs.py           # 第 3 步
│  ├─ download_batches.py      # 第 4 步
│  └─ __init__.py
├─ skills/
│  ├─ html-page-saver/         # PDF 下载 skill，不要删除
│  ├─ rare-earth-literature-extractor/ # Codex CLI 文献提取 skill 
│  └─ review-knowledge-extractor/ # 综述知识提取 skill
│ 
├─ activate_csd.ps1
├─ activate_csd.bat
├─ start.ipynb                 # 推荐操作入口
└─ README.md
```



## 四、MinerU PDF → Markdown

文献提取采用 **Markdown 优先、PDF 兜底** 的流程。先在终端设置 `MINERU_API_KEY`，然后运行 `start.ipynb` 的第 5 步，或执行：

```powershell
python scripts/mineru_pdf_parser.py --limit 5 --model-version vlm
```

首次建议只转换 5 篇。确认输出后去掉 `--limit`。普通文本 PDF 不启用 OCR；扫描件使用 `--ocr`。

输出位置：

```text
documents/md/<PDF文件名>.md          # 只保留 ZIP 中的主 Markdown
data/process_csv/mineru_conversion_log.csv       # 成功、失败、batch_id 与错误信息
```

转换支持断点续跑：只要存在对应的非空 `documents/md/<PDF文件名>.md`，就会跳过。MinerU 返回的 ZIP 只作为临时文件使用，读取主 Markdown 后立即删除，不解压或保存图片、布局 JSON 等资源；需要核对结构式、Scheme、公式或表格时回查原始 PDF。API Token 只能放在环境变量或本地 `.env` 中，不要写入 Notebook、脚本或提交到版本库。

生成 Markdown 后重新执行：

```powershell
python skills/rare-earth-literature-extractor/scripts/build_queue.py
```

队列会优先使用 Markdown，并保留原始 PDF 作为公式、表格、Scheme 或结构对应关系不清时的回查来源。结构卡片不保存 `needs_si`、下载状态或解析状态；缺少定量合成方案的 DOI 仅统计到 `data/process_csv/si_required.csv`。

## 最终本地完整性审核

在更换卡片、CIF 文件或源文档后，使用配置好的 CSD Python 运行 `scripts/audit_integrity.py`。它会通过 DOI 和 CCDC 编号对文章 PDF、SI、正文 Markdown、论文卡片和 CIF 文件进行对账，但不会编辑源文件。

- `data/final_integrity_ledger.csv`：每个 DOI 一行，包含本地路径、结构数量以及卡片缺口。
- `data/final_integrity_issues.csv`：每个未匹配的结构/文件或没有 CCDC 编号的卡片化合物一行。缺少本地 CIF 并不代表 CCDC 没有存档。
- `data/process_csv/final_missing_cif_targets.csv`：需要本地 CIF 导出的卡片 CCDC 编号；在 notebook 中选择 CCDC 编号查找。
- `data/final_synthesis_gaps.csv`：当前基于卡片的合成缺口，取代 `data/process_csv/si_required.csv` 中过时的统计。
- `data/card_review.md`：保留先前的 SI 人工审核记录；生成器在末尾按 DOI/化合物列出当前卡片的具体异常与核查线索。

要查看 `data/` 和 `data/process_csv/` 下每个 CSV 的当前清单，请参阅 `data/README.md`。
供脚本读取的中间队列、索引、CIF 补导出名单和日志位于 `data/process_csv/`；供人工核查的异常报告留在 `data/`。
人工审核报告留在 `data/`；供脚本读取的索引、队列、补导出名单和断点日志位于 `data/process_csv/`。审核不会仅仅根据共享的 DOI 来确定化学身份：在将卡片/CIF 对视为确认前，请先检查每个化合物的例外情况。
CIF 提取器只在唯一匹配的文章化合物报告核数大于 20 时才添加 `candidate_structural_motifs`：
它将身份-对称、共享氧金属图划分为暂定的结构基元，并记录每个基元的金属标签/组成以及基元间氧桥。
这只是一个算法参考，而不是作者定义的结构单元或合成路径。缺失的对称键、部分金属占位、不匹配的位点数量或断开的图会以状态/原因的形式抑制分区。
在 `start.ipynb` 的第29单元格中，`CIF_CARD_EXECUTE=False` 会执行一个三文件候选扫描，但不会写入卡片；将其设置为 `True` 才会写入。现有卡片默认会被跳过；只有在有意刷新卡片时才设置 `CIF_CARD_OVERWRITE=True`，然后在使用它们作为结构数据前，对照图表和附录检查结果。

## 笔记本恢复和对账

一次运行 `start.ipynb` 的一个步骤，而不是全部运行。第4和第5节会跳过已有效的PDF或非空Markdown；如果某项失败，可以通过再次执行同一单元格重试。
非空Markdown仍可能质量较差，所以检查第5.1节。第6节的提取失败有多种原因（包括超时和验证错误），不一定是缺少SI。第6.3节将文章卡片的CCDC标识符与DOI关联的 `data/structures.csv` 进行比较；保存其报告，然后第6.1节可以将目录/卡片不匹配项作为整个卡片重提取的候选。第6.2节仍然使用基于文件夹的方式。提取不会修改审计报告。第7节在现有卡片上使用仅SI的综合补丁。
第7.1节提供了明确的以SI为主的全卡模式，并可选择添加主文章和每个DOI的人为审核备注；验证后的替换会备份之前的卡片。 
第8.1节在第9节的CIF结构卡之前生成大簇列表。
第10节重建本地文件完整性账本。这些单元格默认会预览；在检查输入后再启用相关执行开关。不要把 `data/final_integrity_ledger.csv` 与单独的技能本地 `rare_earth_cluster_skill/cluster_ledger.csv` 混淆。
## 人工审查与程序索引

- `data/card_review.md`：逐 DOI/化合物列出 card 缺陷与核查线索；保留既有 SI 人工审阅历史，末尾自动审计段由 `scripts/audit_integrity.py` 更新。
- `data/final_integrity_issues.csv`、`data/final_synthesis_gaps.csv`、`data/card_ccdc_match_review.csv`：供人工核查的逐项报告；`data/final_integrity_ledger.csv` 是文件完整性总账。
- `data/process_csv/project_card_ledger.csv`：从项目 JSON 卡片重建的程序检索索引（生成：`skills/project-card-corpus/scripts/build_ledger.py`；搜索：`search_ledger.py`），不是人工审查报告，也不同于技能本地的 `rare_earth_cluster_skill/cluster_ledger.csv`。CSV 使用 UTF-8；在旧版 Excel/PowerShell 出现乱码时选择 UTF-8 导入或调整终端编码，不要重编码源卡片。
- `data/process_csv/si_required.csv`、`review_knowledge_index.csv`、`mineru_conversion_log.csv` 和 `final_missing_cif_targets.csv` 是程序的状态/索引/输入；不要当作当前人工审查结论。详细清单见 `data/README.md`。
