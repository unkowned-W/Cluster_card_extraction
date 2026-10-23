# 全项目卡片索引

从项目根目录运行（`python` 指已安装的 Python；本机也可使用 CSD Python 解释器）：

```powershell
python skills/project-card-corpus/scripts/build_ledger.py --check
python skills/project-card-corpus/scripts/build_ledger.py
python skills/project-card-corpus/scripts/search_ledger.py --element Gd --min-nuclearity 20 --limit 10
python skills/project-card-corpus/scripts/search_ledger.py --doi '10.1002/anie.200705731'
```

生成 `data/process_csv/project_card_ledger.csv`；它是可重建索引，不修改或复制 `data/extracted_cards/`、`data/cif_structure_cards/`、`data/review_knowledge_cards/`。新卡片加入后重新构建。字段及证据边界见 `references/ledger_schema.md` 和 `SKILL.md`。

未匹配条目标记为 `no_corresponding_cif`，依据是项目负责人对未匹配项的人工核查；该状态不表示对 CCDC 数据库实时查询的结果。
